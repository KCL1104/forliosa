"""Nightly PostgreSQL backup to an S3-compatible bucket (product owner 2026-11-21).

The worker's ``db_backup`` job (04:00 Taipei) runs ``pg_dump --format=custom`` (compressed; restore with ``pg_restore``)
of the whole database and uploads it with one SigV4-signed PUT to ``postgres/forliosa-<day of month>.dump``. Each night
overwrites the file of the same day last month, so the bucket keeps about a month of dumps with no list or delete calls.
A successful run upserts ``dataset_status`` key ``db-backup`` (data date = the backup day): the admin overview lists it
and flags it once backups stop for 3 trading days. Restore steps: docs/deploy.md (資料庫備份).

ponytail: day-of-month rotation (~30 days kept) and a single PUT (objects up to 5 GB); lifecycle rules and multipart
uploads if either ever falls short.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy.engine import make_url

from forliosa.config import Settings, get_settings
from forliosa.timeutil import now_utc, today_taipei

log = logging.getLogger("forliosa.backup")

STATUS_KEY = "db-backup"
PG_DUMP_TIMEOUT_SECONDS = 3600


def configured(settings: Settings) -> bool:
    s = settings
    return bool(s.backup_s3_endpoint and s.backup_s3_bucket and s.backup_s3_access_key_id
                and s.backup_s3_secret_access_key and s.database_url.startswith("postgresql"))


def object_key(day: date) -> str:
    return f"postgres/forliosa-{day.day:02d}.dump"


def object_url(settings: Settings, key: str) -> str:
    """Virtual-host style: ``https://<bucket>.<endpoint host>/<key>``."""
    ep = urlsplit(settings.backup_s3_endpoint or "")
    return f"{ep.scheme}://{settings.backup_s3_bucket}.{ep.netloc}/{key}"


def sigv4_headers(method: str, url: str, headers: Mapping[str, str], payload_sha256: str, key_id: str, secret: str,
                  region: str, now: datetime) -> dict[str, str]:
    """AWS Signature Version 4 (service ``s3``) for a request without a query string: ``headers`` plus ``host``,
    ``x-amz-date``, ``x-amz-content-sha256`` and ``authorization``. Every header passed in is signed."""
    parts = urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    h = {k.lower(): str(v).strip() for k, v in headers.items()}
    h |= {"host": parts.netloc, "x-amz-content-sha256": payload_sha256, "x-amz-date": amz_date}
    names = sorted(h)
    signed = ";".join(names)
    canonical = "\n".join([method, quote(parts.path or "/", safe="/-_.~"), "", *(f"{k}:{h[k]}" for k in names), "",
                           signed, payload_sha256])
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("AWS4" + secret).encode()
    for part in (day, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    h["authorization"] = f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={signature}"
    return h


def _pg_env(database_url: str) -> dict[str, str]:
    """libpq variables for pg_dump (the password stays out of the command line)."""
    url = make_url(database_url)
    env = {**os.environ, "PGHOST": url.host or "", "PGPORT": str(url.port or 5432), "PGUSER": url.username or "",
           "PGPASSWORD": url.password or "", "PGDATABASE": url.database or ""}
    if sslmode := url.query.get("sslmode"):
        env["PGSSLMODE"] = sslmode if isinstance(sslmode, str) else sslmode[0]
    return env


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def run(settings: Settings | None = None, day: date | None = None) -> str | None:
    """Dump and upload; the object key, or None when backups are not configured. Raises on any failure (the worker
    logs it; ``dataset_status`` then keeps the last good day)."""
    s = settings or get_settings()
    if not configured(s):
        return None
    day = day or today_taipei()
    key = object_key(day)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "forliosa.dump"
        proc = subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={path}"],
                              env=_pg_env(s.database_url), capture_output=True, text=True,
                              timeout=PG_DUMP_TIMEOUT_SECONDS, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
        size = path.stat().st_size
        url = object_url(s, key)
        headers = sigv4_headers("PUT", url, {"content-length": str(size), "content-type": "application/octet-stream"},
                                _sha256(path), s.backup_s3_access_key_id or "",
                                s.backup_s3_secret_access_key.get_secret_value() if s.backup_s3_secret_access_key
                                else "", s.backup_s3_region, now_utc())
        with path.open("rb") as f:
            resp = httpx.put(url, content=f, headers=headers, timeout=httpx.Timeout(60.0, write=None))
        if resp.status_code >= 300:
            raise RuntimeError(f"backup upload failed: HTTP {resp.status_code} {resp.text[:300]}")
    _record(day)
    log.info("database backup: %s (%.1f MB)", key, size / 1e6)
    return key


def _record(day: date) -> None:
    from forliosa.db import session_factory
    from forliosa.models import DatasetStatus

    with session_factory()() as db:
        db.merge(DatasetStatus(key=STATUS_KEY, data_date=day, rows=0, fetched_at=now_utc()))
        db.commit()
