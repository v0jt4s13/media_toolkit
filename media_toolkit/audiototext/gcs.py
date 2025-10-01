"""Google Cloud Storage helpers."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, Optional

from google.api_core.exceptions import Forbidden, GoogleAPIError, NotFound
from google.cloud import storage


def upload_to_gcs(file_path: str, bucket_name: str, prefix: Optional[str] = None) -> str:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    key_prefix = (prefix or os.getenv("GCS_PREFIX") or "stt_uploads/").strip("/")
    blob_name = f"{key_prefix}/{uuid.uuid4().hex}_{os.path.basename(file_path)}"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(file_path, timeout=600)
    return f"gs://{bucket_name}/{blob_name}"


def gcs_selftest(bucket_name: Optional[str] = None, prefix: Optional[str] = None) -> Dict[str, Any]:
    start_ts = time.time()
    info: Dict[str, Any] = {
        "ok": False,
        "bucket": bucket_name or os.getenv("GCS_BUCKET"),
        "prefix": (prefix or os.getenv("GCS_PREFIX") or "stt_uploads/").strip("/"),
        "test_blob": None,
        "roundtrip_ms": None,
        "error": None,
    }

    try:
        bucket_name = info["bucket"]
        if not bucket_name:
            info["error"] = "Missing GCS bucket. Set GCS_BUCKET env var or pass ?bucket=..."
            return info

        client = storage.Client()
        bucket = client.bucket(bucket_name)

        if not bucket.exists(timeout=60):
            info["error"] = f"Bucket '{bucket_name}' does not exist or no permission."
            return info

        blob_name = f"{info['prefix']}/selftest_{uuid.uuid4().hex}.txt"
        blob = bucket.blob(blob_name)
        payload = f"selftest {time.time()}".encode("utf-8")

        blob.upload_from_string(payload, content_type="text/plain", timeout=60)
        blob.reload(timeout=60)
        blob.delete(timeout=60)

        info["test_blob"] = f"gs://{bucket_name}/{blob_name}"
        info["ok"] = True
        info["roundtrip_ms"] = int((time.time() - start_ts) * 1000)
        return info

    except (Forbidden, NotFound) as exc:
        info["error"] = f"{exc.__class__.__name__}: {exc}"
        return info
    except GoogleAPIError as exc:
        info["error"] = f"GoogleAPIError: {exc}"
        return info
    except Exception as exc:  # pragma: no cover - diagnostic fallback
        info["error"] = f"Unexpected: {exc}"
        return info
