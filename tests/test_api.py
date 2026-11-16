from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import quote

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app import main
from app.aws_transcribe import AwsTranscribeService, TranscriptResult
from app.database import JobStore


class ApiTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.store = JobStore(Path(directory) / "jobs.sqlite3")
        self.aws = Mock(spec=AwsTranscribeService)
        self.aws.presigned_upload_url.return_value = "https://example.test/upload"
        self.enterContext(patch.object(main, "store", self.store))
        self.enterContext(patch.object(main, "aws", self.aws))
        self.client = self.enterContext(TestClient(main.app))

    def sign(self, **updates):
        return self.client.post(
            "/api/uploads/sign", json={"filename": "clip.mp4", "size_bytes": 80, **updates}
        )

    def start(self, job_id, uploaded=True):
        return self.client.post(f"/api/jobs/{job_id}/start", json={"uploaded": uploaded})

    def test_home_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertTrue(self.client.get("/health").json()["ok"])

    def test_rejects_bad_upload_before_calling_aws(self):
        self.assertEqual(self.sign(filename="invalid.exe").status_code, 400)
        self.assertEqual(self.sign(size_bytes=main.settings.max_upload_bytes + 1).status_code, 413)
        self.aws.presigned_upload_url.assert_not_called()
        self.assertEqual(self.store.list_recent(), [])

    def test_signing_failure_does_not_leave_a_job(self):
        self.aws.presigned_upload_url.side_effect = RuntimeError("provider detail")
        response = self.sign()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("provider detail", response.text)
        self.assertEqual(self.client.get("/api/jobs").json(), {"jobs": []})

    def test_start_waits_for_upload_and_accepts_a_retry(self):
        job_id = self.sign().json()["job"]["id"]
        self.assertEqual(self.start(job_id, uploaded=False).status_code, 409)
        self.aws.start_transcription.assert_not_called()
        self.aws.start_transcription.side_effect = [RuntimeError("provider detail"), None]
        self.assertEqual(self.start(job_id).status_code, 502)
        self.assertEqual(self.store.get(job_id).status, "waiting_upload")
        self.assertEqual(self.start(job_id).json()["job"]["status"], "processing")
        self.assertEqual(self.start(job_id).json()["job"]["status"], "processing")
        self.assertEqual(self.aws.start_transcription.call_count, 2)

    def test_polling_and_downloads_keep_status_and_unicode(self):
        title = "Revisión 🎬"
        job_id = self.sign(title=title).json()["job"]["id"]
        self.assertEqual(self.start(job_id).status_code, 200)
        self.aws.refresh_transcription.side_effect = [
            RuntimeError("temporary upstream failure"),
            {
                "status": "completed",
                "completed_at": "2026-11-16T12:00:00+00:00",
                "result": TranscriptResult("Hola", "{}", [{"start": 0.0, "end": 1.0, "text": "Hola"}]),
            },
        ]
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").status_code, 502)
        self.assertEqual(self.store.get(job_id).status, "processing")
        completed = self.client.get(f"/api/jobs/{job_id}").json()["job"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["text"], "Hola")
        self.assertEqual(
            self.store.update(job_id, expected_statuses=("processing",), status="failed").status,
            "completed",
        )
        for suffix in ("txt", "srt"):
            response = self.client.get(f"/api/jobs/{job_id}/download.{suffix}")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Hola", response.text)
            self.assertIn("filename*=UTF-8''" + quote(f"{title}.{suffix}", safe=""),
                          response.headers["content-disposition"])

    def test_existing_transcribe_job_can_be_retried_by_name(self):
        job_id = self.sign().json()["job"]["id"]
        record = self.store.get(job_id)
        service = AwsTranscribeService(main.settings)
        transcribe = Mock()
        transcribe.start_transcription_job.side_effect = ClientError(
            {"Error": {"Code": "ConflictException", "Message": "already queued"}},
            "StartTranscriptionJob",
        )
        with patch.object(service, "_client", return_value=transcribe):
            service.start_transcription(record)
        self.assertEqual(
            transcribe.start_transcription_job.call_args.kwargs["TranscriptionJobName"],
            record.transcribe_job_name,
        )
