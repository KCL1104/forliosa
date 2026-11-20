"""Nightly database backup (forliosa.backup): the S3 signature, when it runs, and what one run uploads and records."""

from __future__ import annotations

import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from forliosa import backup
from forliosa.config import Settings
from forliosa.db import session_factory
from forliosa.models import DatasetStatus

BUCKET = {"backup_s3_endpoint": "https://t3.example.dev", "backup_s3_bucket": "db-backups-x",
          "backup_s3_access_key_id": "AK", "backup_s3_secret_access_key": "SK"}


def test_signature_matches_the_aws_documented_example():
    # "Example: GET Object" in the Amazon S3 Signature Version 4 documentation
    h = backup.sigv4_headers("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
                             "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                             "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1",
                             datetime(2013, 5, 24, tzinfo=UTC))
    assert h["authorization"].endswith("SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                                       "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


def test_only_postgres_with_the_whole_bucket_config_is_backed_up():
    pg = "postgresql://u:p@db:5432/forliosa"
    assert backup.configured(Settings(database_url=pg, **BUCKET))
    assert not backup.configured(Settings(database_url="sqlite:///./x.db", **BUCKET))
    assert not backup.configured(Settings(database_url=pg, **{**BUCKET, "backup_s3_secret_access_key": " "}))
    assert backup.run(Settings(database_url="sqlite:///./x.db", **BUCKET)) is None


def test_one_run_uploads_the_dump_of_that_day_and_records_it(engine, monkeypatch):
    settings = Settings(database_url="postgresql://u:secret@db:5432/forliosa", **BUCKET)
    seen: dict = {}

    def fake_pg_dump(cmd, env, **_kw):
        seen["env_password"] = env["PGPASSWORD"]
        seen["cmd"] = cmd
        Path(cmd[-1].removeprefix("--file=")).write_bytes(b"PGDMP fake")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_put(url, content, headers, timeout):
        seen["url"], seen["body"], seen["headers"] = url, content.read(), headers
        return httpx.Response(200)

    monkeypatch.setattr(backup.subprocess, "run", fake_pg_dump)
    monkeypatch.setattr(backup.httpx, "put", fake_put)

    assert backup.run(settings, day=date(2026, 11, 21)) == "postgres/forliosa-21.dump"
    assert seen["url"] == "https://db-backups-x.t3.example.dev/postgres/forliosa-21.dump"
    assert seen["body"] == b"PGDMP fake"
    assert seen["headers"]["content-length"] == "10"
    assert seen["env_password"] == "secret" and not any("secret" in part for part in seen["cmd"])
    with session_factory()() as db:
        row = db.scalar(select(DatasetStatus).where(DatasetStatus.key == backup.STATUS_KEY))
        assert row is not None and row.data_date == date(2026, 11, 21)
