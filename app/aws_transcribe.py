from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from botocore.exceptions import ClientError

from .config import Settings
from .database import JobRecord, now_iso


SUPPORTED_MEDIA_FORMATS = {"mp3", "mp4", "wav", "flac", "ogg", "amr", "webm", "m4a"}


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    raw_json: str
    segments: list[dict[str, Any]]


def clean_extension(filename: str) -> str:
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_MEDIA_FORMATS:
        raise ValueError(
            "Formato no soportado. Usá mp3, mp4, wav, flac, ogg, amr, webm o m4a."
        )
    return suffix


def safe_title(filename: str) -> str:
    base = PurePosixPath(filename.replace("\\", "/")).stem.strip()
    cleaned = re.sub(r"\s+", " ", base)
    return cleaned[:120] or "Transcripcion"


def make_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        start = _srt_clock(float(segment.get("start", 0)))
        end = _srt_clock(float(segment.get("end", 0)))
        text = str(segment.get("text", "")).strip()
        if text:
            blocks.append(f"{index}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def parse_transcribe_json(payload: dict[str, Any]) -> TranscriptResult:
    results = payload.get("results", {})
    text = ""
    transcripts = results.get("transcripts") or []
    if transcripts:
        text = str(transcripts[0].get("transcript", "")).strip()

    audio_segments = results.get("audio_segments")
    if isinstance(audio_segments, list) and audio_segments:
        segments = [
            {
                "start": float(item.get("start_time", 0) or 0),
                "end": float(item.get("end_time", 0) or 0),
                "text": str(item.get("transcript", "")).strip(),
            }
            for item in audio_segments
            if str(item.get("transcript", "")).strip()
        ]
    else:
        segments = _segments_from_items(results.get("items") or [])

    if not text:
        text = " ".join(segment["text"] for segment in segments).strip()

    return TranscriptResult(
        text=text,
        raw_json=json.dumps(payload, ensure_ascii=False),
        segments=segments,
    )


def _segments_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current_words: list[str] = []
    current_start: float | None = None
    current_end: float | None = None

    for item in items:
        kind = item.get("type")
        alternatives = item.get("alternatives") or []
        content = str((alternatives[0] if alternatives else {}).get("content", "")).strip()
        if not content:
            continue

        if kind == "punctuation":
            if current_words:
                current_words[-1] += content
                if content in {".", "?", "!"}:
                    _flush_segment(segments, current_words, current_start, current_end)
                    current_words = []
                    current_start = None
                    current_end = None
            continue

        start = float(item.get("start_time", current_end or 0) or 0)
        end = float(item.get("end_time", start) or start)
        if current_start is None:
            current_start = start
        current_end = end
        current_words.append(content)

        if current_start is not None and end - current_start >= 8:
            _flush_segment(segments, current_words, current_start, current_end)
            current_words = []
            current_start = None
            current_end = None

    _flush_segment(segments, current_words, current_start, current_end)
    return segments


def _flush_segment(
    segments: list[dict[str, Any]],
    words: list[str],
    start: float | None,
    end: float | None,
) -> None:
    text = " ".join(words).strip()
    if not text or start is None:
        return
    segment_end = end if end is not None and end > start else start + 1.0
    segments.append({"start": round(start, 3), "end": round(segment_end, 3), "text": text})


def _srt_clock(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


class AwsTranscribeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self, service: str):
        self.settings.require_aws()
        import boto3

        return boto3.client(service, region_name=self.settings.aws_region)

    def presigned_upload_url(self, key: str, content_type: str) -> str:
        s3 = self._client("s3")
        return s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": key,
                "ContentType": content_type or "application/octet-stream",
            },
            ExpiresIn=self.settings.presign_ttl_seconds,
            HttpMethod="PUT",
        )

    def presigned_media_url(self, key: str) -> str:
        s3 = self._client("s3")
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key},
            ExpiresIn=self.settings.presign_ttl_seconds,
            HttpMethod="GET",
        )

    def start_transcription(self, record: JobRecord) -> None:
        transcribe = self._client("transcribe")
        request: dict[str, Any] = {
            "TranscriptionJobName": record.transcribe_job_name,
            "Media": {
                "MediaFileUri": f"s3://{self.settings.s3_bucket}/{record.s3_media_key}"
            },
            "MediaFormat": record.media_format,
            "OutputBucketName": self.settings.s3_bucket,
            "OutputKey": record.s3_output_key,
            "Subtitles": {"Formats": ["srt", "vtt"], "OutputStartIndex": 1},
            "Tags": [{"Key": "app", "Value": "vozario-web"}],
        }
        if record.identify_language:
            request["IdentifyLanguage"] = True
            request["LanguageOptions"] = ["es-ES", "es-US", "en-US"]
        else:
            request["LanguageCode"] = record.language_code
        if record.speaker_labels:
            request["Settings"] = {"ShowSpeakerLabels": True, "MaxSpeakerLabels": 6}
        try:
            transcribe.start_transcription_job(**request)
        except ClientError as exc:
            # A retry uses the same UUID-based job name as the original request.
            if exc.response["Error"]["Code"] != "ConflictException":
                raise

    def refresh_transcription(self, record: JobRecord) -> dict[str, Any]:
        transcribe = self._client("transcribe")
        job = transcribe.get_transcription_job(
            TranscriptionJobName=record.transcribe_job_name
        )["TranscriptionJob"]
        status = job.get("TranscriptionJobStatus", "IN_PROGRESS")
        if status == "COMPLETED":
            result = self.read_output(record.s3_output_key)
            return {
                "status": "completed",
                "transcribe_status": status,
                "completed_at": now_iso(),
                "result": result,
            }
        if status == "FAILED":
            return {
                "status": "failed",
                "transcribe_status": status,
                "failure_reason": job.get("FailureReason", "Amazon Transcribe fallo."),
            }
        return {"status": "processing", "transcribe_status": status}

    def read_output(self, output_key: str) -> TranscriptResult:
        s3 = self._client("s3")
        body = s3.get_object(Bucket=self.settings.s3_bucket, Key=output_key)["Body"].read()
        return parse_transcribe_json(json.loads(body.decode("utf-8")))

