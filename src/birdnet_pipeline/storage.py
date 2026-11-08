"""Read and write files at local paths or gs:// URIs with the same calls.

The same code runs on a laptop (local folders) and in Cloud Run (bucket
paths). gs:// access uses google-cloud-storage with the environment's
credentials (the job's service account in Cloud Run).
"""
from pathlib import Path


def is_gcs(path) -> bool:
    return str(path).startswith("gs://")


def join(base, *parts) -> str:
    base = str(base).rstrip("/")
    return "/".join([base, *[str(p).strip("/") for p in parts]])


def _split(uri: str):
    bucket, _, name = uri[len("gs://"):].partition("/")
    return bucket, name


_client = None


def _bucket_blob(uri: str):
    global _client
    from google.cloud import storage

    if _client is None:
        _client = storage.Client()
    bucket, name = _split(uri)
    return _client.bucket(bucket).blob(name)


def exists(path) -> bool:
    return _bucket_blob(str(path)).exists() if is_gcs(path) else Path(path).exists()


def read_text(path) -> str:
    return _bucket_blob(str(path)).download_as_text() if is_gcs(path) else Path(path).read_text()


def download(path, local: Path) -> Path:
    """Copy path (local or gs://) to a local file; returns the local path."""
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    if is_gcs(path):
        _bucket_blob(str(path)).download_to_filename(str(local))
    else:
        local.write_bytes(Path(path).read_bytes())
    return local


def write_bytes(path, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Write bytes; for local paths, write to a temp file and rename so readers never see partial files."""
    if is_gcs(path):
        _bucket_blob(str(path)).upload_from_string(data, content_type=content_type)
    else:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
