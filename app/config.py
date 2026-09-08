from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    s3_bucket: str = os.getenv("VOZARIO_S3_BUCKET", "")
    input_prefix: str = os.getenv("VOZARIO_S3_INPUT_PREFIX", "uploads")
    output_prefix: str = os.getenv("VOZARIO_S3_OUTPUT_PREFIX", "transcripts")
    public_base_url: str = os.getenv("VOZARIO_PUBLIC_BASE_URL", "http://localhost:8000")
    sqlite_path: Path = Path(os.getenv("VOZARIO_SQLITE_PATH", "data/vozario_web.sqlite3"))
    max_upload_mb: int = _int_env("VOZARIO_MAX_UPLOAD_MB", 2048)
    presign_ttl_seconds: int = _int_env("VOZARIO_PRESIGN_TTL_SECONDS", 3600)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def require_aws(self) -> None:
        if not self.s3_bucket:
            raise RuntimeError("Falta configurar VOZARIO_S3_BUCKET.")


settings = Settings()

