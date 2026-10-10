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
import shutil
import subprocess
import sys
import tempfile

from pilot_ci_evidence_restore import EvidenceRestoreError, restore_and_reconcile

SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
TEST_DB = "mcri_performance"
TEST_USER = "mcri_performance"
CLONE_DB = "mcri_ci_restore_probe"
SYNTHETIC_REF = "MCRI-DEMO-MT-ORION"
COMPOSE_WRITERS = (
    "web", "api", "worker", "governance-webhook-worker",
    "external-evidence-scheduler-worker",
    "external-evidence-observation-worker",
    "external-evidence-review-projector-worker",
    "demo-seed", "preflight", "migrate",
)
EXPECTED_RUNNING_AFTER_STOP = frozenset(("db", "clamav"))

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


def expect_integrity_rejection(command: list[str], env: dict[str, str],
                               *, timeout: int = 60) -> None:
    """A tampered disposable artifact MUST fail an existing read-only verifier.

    Suppress raw stdout/stderr; a successful exit here is a hard failure.
    """
    try:
        result = subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout,
                                check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeError("synthetic corruption rejection could not be observed") from None
    if result.returncode == 0:
        raise ProbeError("synthetic corrupted recovery artifact was accepted")


def prove_tamper_detection(dump: Path, archive: Path, manifest: Path,
                           release_sha: str, env: dict[str, str]) -> None:
    """Mutate COPIES ONLY, checking production backup and pair verifiers."""
    damaged_dir = dump.parent / "deliberately-corrupted"
    damaged_dir.mkdir(mode=0o700)
    corrupted_dump = damaged_dir / dump.name
    for original, copy in (
        (dump, corrupted_dump),
        (Path(str(dump) + ".sha256"), Path(str(corrupted_dump) + ".sha256")),
        (Path(str(dump) + ".meta"), Path(str(corrupted_dump) + ".meta")),
    ):
        shutil.copyfile(original, copy)
    # Append after copying checksum/metadata: preserve identity/name but
    # invalidate the protected SHA before pg_restore --list is reached.
    with corrupted_dump.open("ab") as stream:
        stream.write(b"synthetic-intentional-corruption")
    expect_integrity_rejection(
        ["bash", "scripts/verify_postgres_backup.sh", str(corrupted_dump)], env)

    corrupted_archive = damaged_dir / archive.name
    shutil.copyfile(archive, corrupted_archive)
    # A tar reader may ignore trailing bytes; the recorded SHA still MUST
    # reject an altered archive even when the original tar members parse.
    with corrupted_archive.open("ab") as stream:
        stream.write(b"synthetic-intentional-corruption")
    expect_integrity_rejection(
        ["python", "scripts/pilot_recovery_pair.py", "verify",
         "--db-dump", str(dump), "--evidence-archive", str(corrupted_archive),
         "--release-sha", release_sha, "--manifest", str(manifest)], env)


def quiesce_compose_writers(env_file: str, env: dict[str, str]) -> None:
    """Stop every application writer, then independently inspect running services.

    This is allowed ONLY by the synthetic environment guard in observe().
    Never use this helper on a real/customer data Compose environment.
    """
    _run(_compose(env_file, "stop", *COMPOSE_WRITERS), env=env, timeout=90)
    running = _run(_compose(env_file, "ps", "--status", "running", "--services"),
                   env=env, timeout=30)
    names = running.splitlines()
    if (len(names) != len(set(names))
        or set(names) != EXPECTED_RUNNING_AFTER_STOP):
        raise ProbeError("synthetic Compose writer quiescence not independently verified")


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
    document_sql = (
        "SELECT COALESCE(json_agg(json_build_object("
        "'key', d.storage_key, 'sha256', d.file_hash, 'size', d.file_size_bytes"
        ") ORDER BY d.storage_key)::text, '[]') "
        "FROM documents d JOIN claims c ON c.id=d.claim_id "
        "WHERE c.external_reference='MCRI-DEMO-MT-ORION';"
    )
    version_sql = ("SELECT COALESCE(string_agg(version_num, ',' ORDER BY version_num), '') "
                   "FROM alembic_version;")
    # All performance/API checks have finished. Stop every known writer
    # *before* reading the baseline or recording backup bytes. A failed
    # stop/verification aborts without making a database dump or archive.
    quiesce_compose_writers(env_file, env)
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
                    _compose(env_file, "run", "--rm", "--no-deps", "-T",
                             "--entrypoint", "python", "api", "-c", ARCHIVE_PROG),
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
              "--quiescence-ref", "synthetic-ci-compose-writers-stopped",
              "--output", str(manifest)], env=env)
        _run(["python", "scripts/pilot_recovery_pair.py", "verify",
              "--db-dump", str(dump), "--evidence-archive", str(archive),
              "--release-sha", actual_checkout,
              "--manifest", str(manifest)], env=env)

        # Deliberate tamper occurs on separate copies ONLY. The two existing
        # read-only integrity verifiers must reject altered bytes before any
        # clone restoration is attempted.
        prove_tamper_detection(dump, archive, manifest, actual_checkout, env)

        # Target only a NEW constant name, never the running application's DB.
        # If creation fails, do not drop a pre-existing database.
        created = False
        verified = False
        recovered_counts = None
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
            if not verified:
                raise ProbeError("synthetic cloned database verification failed")
            # Restore files only to a fresh isolated temp directory, NEVER the
            # application storage volume; compare bytes with the restored DB.
            restored_rows = _query(env_file, env, CLONE_DB, document_sql)
            with tempfile.TemporaryDirectory(prefix="mcri-ci-evidence-restore-") as temp:
                try:
                    recovered_counts = restore_and_reconcile(
                        archive, Path(temp), restored_rows)
                except EvidenceRestoreError:
                    raise ProbeError("synthetic Evidence-to-Document reconciliation failed") from None
        finally:
            if created:
                # On an unsuccessful clone/cleanup the aggregate CI gate fails.
                _run(_compose(env_file, "exec", "-T", "db", "dropdb",
                              "-U", TEST_USER, "--if-exists", "--force",
                              CLONE_DB), env=env)
        if not verified or recovered_counts is None:
            raise ProbeError("synthetic cloned database or Evidence verification failed")

    return {
        "schema": "mcri-synthetic-ci-recovery-probe-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "observed_checkout_sha": actual_checkout,
        "environment": "ephemeral_ci_synthetic_only",
        "postgres_dump_archive_validated": True,
        "postgres_backup_sidecars_reverified": True,
        "evidence_archive_integrity_bound": True,
        "corrupted_db_dump_rejected": True,
        "corrupted_evidence_archive_rejected": True,
        "compose_writer_quiescence_verified": True,
        "external_writer_quiescence_verified": False,
        "isolated_db_clone_restored": True,
        "synthetic_claim_count_and_migration_matched": True,
        "isolated_evidence_files_restored": recovered_counts["files_restored"],
        "restored_demo_document_hashes_matched": recovered_counts["demo_documents_matched"],
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
