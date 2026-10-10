#!/usr/bin/env python3
"""CI-only, non-destructive synthetic PostgreSQL restore + Evidence archive probe.

Only for an existing ephemeral .env.performance Docker Compose stack; never
runs restore_postgres.sh, deletes the application DB, restores Evidence to the
live volume, or grants Pilot approval. Explicitly does not prove a matching
DB/Evidence snapshot, real-host recovery or operator authorization.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
TEST_DB = "mcri_performance"
TEST_USER = "mcri_performance"
CLONE_DB = "mcri_ci_restore_probe"
SYNTHETIC_REF = "MCRI-DEMO-MT-ORION"

# Streams the actual synthetic Evidence volume into an ephemeral PRIVATE tar.
# No path/bytes printed. Reject non-regular file and symlink members.
ARCHIVE_PROG = r"""
import os, sys, tarfile
from pathlib import Path
root = Path("/data/documents")
if not root.is_dir():
    raise SystemExit(3)
count = 0
total = 0
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            if (Path(base) / name).is_symlink():
                raise SystemExit(4)
        for name in sorted(files):
            path = Path(base) / name
            if path.is_symlink() or not path.is_file():
                raise SystemExit(4)
            count += 1
            total += path.stat().st_size
            if count > 5000 or total > 2 * 1024 * 1024 * 1024:
                raise SystemExit(5)
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(root)))
            if not info.isfile():
                raise SystemExit(6)
            with path.open("rb") as source:
                archive.addfile(info, fileobj=source)
if not count:
    raise SystemExit(7)
"""


class ProbeError(RuntimeError):
    """Bounded error category: does not contain Docker output or secret data."""


def _run(cmd: list[str], *, env: dict[str, str],
         stdin_file: Path | None = None, timeout: int = 180) -> str:
    try:
        if stdin_file is None:
            proc = subprocess.run(cmd, env=env, text=True, capture_output=True,
                                  timeout=timeout, check=False)
        else:
            with stdin_file.open("rb") as source:
                proc = subprocess.run(cmd, env=env, stdin=source, text=True,
                                      capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeError("bounded synthetic restore step unavailable") from None
    if proc.returncode:
        # Never surface raw SQL, Git, Compose errors, paths, usernames or passwords.
        raise ProbeError("bounded synthetic restore step failed")
    return proc.stdout.strip()


def _compose(env_file: str, *args: str) -> list[str]:
    return ["docker", "compose", "--env-file", env_file, *args]


def _query(env_file: str, env: dict[str, str], db: str, sql: str) -> str:
    return _run(_compose(env_file, "exec", "-T", "db", "psql", "-U",
                         TEST_USER, "-d", db, "-At", "-c", sql), env=env)


def validate_guard(env_file: str, environ: dict[str, str]) -> None:
    if (env_file != ".env.performance"
        or environ.get("APP_ENV") != "test"
        or environ.get("MCRI_CI_RESTORE_PROBE") != "1"
        or environ.get("POSTGRES_DB") != TEST_DB
        or environ.get("POSTGRES_USER") != TEST_USER):
        raise ProbeError("CI-only synthetic environment guard not satisfied")


def observe(*, env_file: str, env: dict[str, str]) -> dict:
    validate_guard(env_file, env)
    actual_checkout = _run(["git", "rev-parse", "HEAD"], env=env)
    if not SHA_RE.fullmatch(actual_checkout):
        raise ProbeError("actual checkout commit SHA unavailable")
    env = {**env, "COMPOSE_ENV_FILES": env_file}
    ref_count_sql = ("SELECT COUNT(*) FROM claims WHERE external_reference = "
                     "'MCRI-DEMO-MT-ORION';")
    version_sql = ("SELECT COALESCE(string_agg(version_num, ',' ORDER BY version_num), '') "
                   "FROM alembic_version;")
    source_count = _query(env_file, env, TEST_DB, ref_count_sql)
    source_revision = _query(env_file, env, TEST_DB, version_sql)
    if source_count != "1" or not source_revision:
        raise ProbeError("synthetic MT ORION seed or Alembic baseline unavailable")

    with tempfile.TemporaryDirectory(prefix="mcri-ci-recovery-") as work:
        root = Path(work)
        dump = root / "synthetic.dump"
        archive = root / "synthetic-evidence.tar"
        manifest = root / "pair.json"

        # These existing scripts operate on the synthetic Docker Compose DB.
        _run(["bash", "scripts/backup_postgres.sh", str(dump)], env=env, timeout=240)
        _run(["bash", "scripts/verify_postgres_backup.sh", str(dump)], env=env)

        try:
            with archive.open("xb") as destination:
                proc = subprocess.run(
                    _compose(env_file, "exec", "-T", "api", "python", "-c",
                             ARCHIVE_PROG),
                    env=env, stdout=destination, stderr=subprocess.DEVNULL,
                    timeout=120, check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
            raise ProbeError("synthetic Evidence archive capture unavailable") from None
        if proc.returncode != 0 or archive.stat().st_size == 0:
            raise ProbeError("synthetic Evidence archive capture failed")

        _run(["python", "scripts/pilot_recovery_pair.py", "create",
              "--db-dump", str(dump), "--evidence-archive", str(archive),
              "--release-sha", actual_checkout,
              "--quiescence-ref", "synthetic-ci-not-quiescence",
              "--output", str(manifest)], env=env)
        _run(["python", "scripts/pilot_recovery_pair.py", "verify",
              "--db-dump", str(dump), "--evidence-archive", str(archive),
              "--release-sha", actual_checkout,
              "--manifest", str(manifest)], env=env)

        # Target only a NEW constant name, never the running application's DB.
        # If creation fails, do not drop a pre-existing database.
        created = False
        verified = False
        try:
            _run(_compose(env_file, "exec", "-T", "db", "createdb",
                          "-U", TEST_USER, CLONE_DB), env=env)
            created = True
            _run(_compose(env_file, "exec", "-T", "db", "pg_restore", "-U",
                          TEST_USER, "-d", CLONE_DB, "--no-owner",
                          "--no-privileges"), env=env, stdin_file=dump, timeout=240)
            clone_count = _query(env_file, env, CLONE_DB, ref_count_sql)
            clone_revision = _query(env_file, env, CLONE_DB, version_sql)
            verified = clone_count == source_count and clone_revision == source_revision
        finally:
            if created:
                # On an unsuccessful clone/cleanup the aggregate CI gate fails.
                _run(_compose(env_file, "exec", "-T", "db", "dropdb",
                              "-U", TEST_USER, "--if-exists", "--force",
                              CLONE_DB), env=env)
        if not verified:
            raise ProbeError("synthetic cloned database verification failed")

    return {
        "schema": "mcri-synthetic-ci-recovery-probe-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "observed_checkout_sha": actual_checkout,
        "environment": "ephemeral_ci_synthetic_only",
        "postgres_dump_archive_validated": True,
        "postgres_backup_sidecars_reverified": True,
        "evidence_archive_integrity_bound": True,
        "isolated_db_clone_restored": True,
        "synthetic_claim_count_and_migration_matched": True,
        "active_application_db_restored_or_dropped": False,
        "matched_recovery_point_verified": False,
        "evidence_restore_verified": False,
        "full_restore_drill_verified": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = observe(env_file=args.env_file, env=dict(os.environ))
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except ProbeError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot exclusively create synthetic restore record",
              file=sys.stderr)
        return 2
    print("SYNTHETIC CI DB CLONE + EVIDENCE ARCHIVE INTEGRITY PASS.")
    print("This does not prove a matched snapshot or authorize Pilot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
