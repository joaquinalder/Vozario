from __future__ import annotations

import json
import re
import uuid
from pathlib import PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .aws_transcribe import AwsTranscribeService, clean_extension, make_srt, safe_title
from .config import settings
from .database import JobRecord, JobStore


APP_ROOT = PurePosixPath(__file__).parent

app = FastAPI(title="Vozario Web", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
store = JobStore(settings.sqlite_path)
aws = AwsTranscribeService(settings)


class SignUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=260)
    content_type: str = "application/octet-stream"
    size_bytes: int = Field(gt=0)
    title: str = ""
    language_code: str = "es-ES"
    identify_language: bool = False
    speaker_labels: bool = False


class StartJobRequest(BaseModel):
    uploaded: bool = True


def record_to_api(record: JobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "originalFilename": record.original_filename,
        "status": record.status,
        "languageCode": record.language_code,
        "identifyLanguage": bool(record.identify_language),
        "speakerLabels": bool(record.speaker_labels),
        "sizeBytes": record.size_bytes,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "completedAt": record.completed_at,
        "failureReason": record.failure_reason,
        "text": record.transcript_text,
        "segments": record.segments,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "max_upload_mb": settings.max_upload_mb,
            "has_bucket": bool(settings.s3_bucket),
        },
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "awsBucketConfigured": bool(settings.s3_bucket)}


@app.post("/api/uploads/sign")
def sign_upload(payload: SignUploadRequest) -> dict[str, Any]:
    if payload.size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el limite de {settings.max_upload_mb} MB.",
        )
    media_format = clean_extension(payload.filename)
    job_id = uuid.uuid4().hex
    job_name = f"vozario-{job_id}"
    safe_name = _safe_key_name(payload.filename)
    media_key = f"{settings.input_prefix.strip('/')}/{job_id}/{safe_name}"
    output_key = f"{settings.output_prefix.strip('/')}/{job_name}.json"
    title = payload.title.strip()[:140] or safe_title(payload.filename)
    language_code = payload.language_code if payload.language_code != "auto" else "es-ES"

    record = store.create(
        id=job_id,
        title=title,
        original_filename=payload.filename,
        status="waiting_upload",
        language_code=language_code,
        identify_language=1 if payload.identify_language or payload.language_code == "auto" else 0,
        speaker_labels=1 if payload.speaker_labels else 0,
        s3_media_key=media_key,
        s3_output_key=output_key,
        media_format=media_format,
        media_content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        transcribe_job_name=job_name,
    )
    try:
        upload_url = aws.presigned_upload_url(media_key, payload.content_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "job": record_to_api(record),
        "uploadUrl": upload_url,
        "uploadHeaders": {"Content-Type": payload.content_type or "application/octet-stream"},
    }


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str, _: StartJobRequest) -> dict[str, Any]:
    record = _get_job(job_id)
    if record.status not in {"waiting_upload", "failed"}:
        return {"job": record_to_api(record)}
    record = store.update(job_id, status="queued", failure_reason="")
    try:
        aws.start_transcription(record)
    except Exception as exc:
        record = store.update(job_id, status="failed", failure_reason=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record = store.update(job_id, status="processing")
    return {"job": record_to_api(record)}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": [record_to_api(record) for record in store.list_recent()]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    record = _get_job(job_id)
    if record.status in {"queued", "processing"}:
        record = _refresh(record)
    return {"job": record_to_api(record)}


@app.get("/api/jobs/{job_id}/media-url")
def media_url(job_id: str) -> dict[str, str]:
    record = _get_job(job_id)
    try:
        return {"url": aws.presigned_media_url(record.s3_media_key)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/download.txt", response_class=PlainTextResponse)
def download_text(job_id: str) -> PlainTextResponse:
    record = _get_job(job_id)
    return PlainTextResponse(
        record.transcript_text or "",
        headers={"Content-Disposition": f'attachment; filename="{record.title}.txt"'},
    )


@app.get("/api/jobs/{job_id}/download.srt", response_class=PlainTextResponse)
def download_srt(job_id: str) -> PlainTextResponse:
    record = _get_job(job_id)
    return PlainTextResponse(
        make_srt(record.segments),
        headers={"Content-Disposition": f'attachment; filename="{record.title}.srt"'},
    )


@app.exception_handler(ValueError)
def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _refresh(record: JobRecord) -> JobRecord:
    try:
        refresh = aws.refresh_transcription(record)
    except Exception as exc:
        return store.update(record.id, status="failed", failure_reason=str(exc))
    if refresh["status"] == "completed":
        result = refresh["result"]
        return store.update(
            record.id,
            status="completed",
            transcript_text=result.text,
            transcript_json=result.raw_json,
            segments_json=json.dumps(result.segments, ensure_ascii=False),
            completed_at=refresh["completed_at"],
            failure_reason="",
        )
    if refresh["status"] == "failed":
        return store.update(
            record.id,
            status="failed",
            failure_reason=refresh.get("failure_reason", "Amazon Transcribe fallo."),
        )
    return store.update(record.id, status="processing")


def _get_job(job_id: str) -> JobRecord:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No existe esa transcripcion.")
    return record


def _safe_key_name(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip(".-")
    return name[:180] or "video.mp4"

