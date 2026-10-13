#!/usr/bin/env python3
"""Real CI-only restore into a SECOND, disconnected PostgreSQL 18.4 engine.

The isolated, ephemeral database container is NOT the running Compose DB and
publishes no TCP ports. Every query goes over docker exec's local socket.
Synthetic-only guard; no customer environment, fresh-host or release approval.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Callable

from pilot_ci_evidence_restore import EvidenceRestoreError, restore_and_reconcile
from pilot_ci_lineage_reconcile import LineageError, collect_lineage, reconcile

SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
DB_NAME = "mcri_ci_independent_restore"
DB_USER = "mcri_performance"
POSTGRES_IMAGE = "postgres:18.4"
PASSWORD_MIN_LENGTH = 12
READY_ATTEMPTS = 60


class IndependentRestoreError(RuntimeError):
    """Private and bounded; do not expose Postgres diagnostics or credentials."""


def _fixed_phase(command: list[str]) -> str:
    """Derive one bounded operation stage, never expose argv/SQL/secrets."""
    if command[:2] == ["docker", "run"]:
        return "container_start"
    if command[:2] == ["docker", "rm"]:
        return "container_cleanup"
    if "pg_isready" in command:
        return "database_ready"
    if "pg_restore" in command:
        return "archive_restore"
    if "psql" in command:
        return "sql_readback"
    return "operation"


def _run(command: list[str], *, stdin_file: Path | None = None,
         timeout: int = 120) -> str:
    phase = _fixed_phase(command)
    try:
        if stdin_file is None:
            result = subprocess.run(command, text=True, capture_output=True,
                                    timeout=timeout, check=False)
        else:
            with stdin_file.open("rb") as source:
                result = subprocess.run(command, stdin=source, text=True,
                                        capture_output=True, timeout=timeout,
                                        check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise IndependentRestoreError(f"isolated PostgreSQL {phase} unavailable") from None
    if result.returncode != 0:
        raise IndependentRestoreError(f"isolated PostgreSQL {phase} failed")
    return result.stdout.strip()


def _query(container: str, sql: str) -> str:
    return _run(["docker", "exec", container, "psql",
                 "-U", DB_USER, "-d", DB_NAME, "-At", "-c", sql])


def _valid_env(env: dict[str, str], release_sha: str) -> str:
    password = env.get("POSTGRES_PASSWORD")
    if (env.get("APP_ENV") != "test"
        or env.get("MCRI_CI_RESTORE_PROBE") != "1"
        or env.get("POSTGRES_DB") != "mcri_performance"
        or env.get("POSTGRES_USER") != DB_USER
        or not SHA_RE.fullmatch(release_sha)
        or not isinstance(password, str)
        or len(password) < PASSWORD_MIN_LENGTH
        or any(character in password for character in ("\n", "\r", "\x00"))):
        raise IndependentRestoreError("isolated CI PostgreSQL environment guard failed")
    return password


def restore_and_verify(*, dump: Path, archive: Path, release_sha: str,
                       expected_claim_count: str, expected_revision: str,
                       source_lineage: dict[str, tuple[int, str]],
                       env: dict[str, str]) -> dict[str, int | bool]:
    password = _valid_env(env, release_sha)
    if (not dump.is_file() or not archive.is_file()
        or dump.stat().st_size == 0 or archive.stat().st_size == 0):
        raise IndependentRestoreError("isolated recovery artifacts unavailable")
    # An exact SHA-scoped name is unique per workflow head on the ephemeral CI
    # runner. A pre-existing container makes docker run fail, and MUST NOT be
    # stopped or deleted: cleanup is permitted only AFTER our run succeeded.
    name = "mcri-ci-independent-" + release_sha[:16]
    started = False
    with tempfile.TemporaryDirectory(prefix="mcri-isolated-pg-secret-") as temp:
        password_file = Path(temp) / "postgres.env"
        password_file.write_text("POSTGRES_PASSWORD=" + password + "\n", encoding="utf-8")
        password_file.chmod(0o600)
        try:
            _run([
                "docker", "run", "-d", "--rm",
                "--name", name,
                "--network", "none",
                "--security-opt", "no-new-privileges",
                "--pids-limit", "256",
                "--env-file", str(password_file),
                "-e", "POSTGRES_USER=" + DB_USER,
                "-e", "POSTGRES_DB=" + DB_NAME,
                POSTGRES_IMAGE,
            ], timeout=120)
            started = True
            # pg_isready can succeed against the temporary server used by
            # postgres' entrypoint during initdb. That server is shut down
            # before PID 1 execs the final postgres daemon; a pg_restore
            # launched between those two servers can fail spuriously.
            # Require the final PID 1 executable and two successive SQL
            # readbacks with a bounded gap. Never retry a failed pg_restore
            # against a potentially partially written database.
            consecutive_ready = 0
            for iteration in range(READY_ATTEMPTS):
                try:
                    is_final_daemon = (
                        _run(["docker", "exec", name, "cat", "/proc/1/comm"],
                             timeout=5) == "postgres"
                    )
                    if is_final_daemon:
                        _run(["docker", "exec", name, "pg_isready",
                              "-U", DB_USER, "-d", DB_NAME], timeout=5)
                        is_final_daemon = (_query(name, "SELECT 1;") == "1")
                    consecutive_ready = consecutive_ready + 1 if is_final_daemon else 0
                    if consecutive_ready >= 2:
                        break
                except IndependentRestoreError:
                    consecutive_ready = 0
                if iteration + 1 < READY_ATTEMPTS:
                    time.sleep(1)
            if consecutive_ready < 2:
                raise IndependentRestoreError("independent PostgreSQL engine did not become ready")

            # pg_restore runs in a completely distinct PostgreSQL process and
            # data volume with network disabled. It never targets the active
            # Compose database or changes any production storage.
            _run(["docker", "exec", "-i", name, "pg_restore",
                  "-U", DB_USER, "-d", DB_NAME,
                  "--no-owner", "--no-privileges"],
                 stdin_file=dump, timeout=240)
            count_sql = ("SELECT COUNT(*) FROM claims WHERE external_reference="
                         "'MCRI-DEMO-MT-ORION';")
            revision_sql = ("SELECT COALESCE(string_agg(version_num, ',' ORDER BY version_num),'')"
                            " FROM alembic_version;")
            if (_query(name, count_sql) != expected_claim_count
                or _query(name, revision_sql) != expected_revision):
                raise IndependentRestoreError("independent PostgreSQL claim or migration changed")
            try:
                lineage = collect_lineage(DB_NAME, lambda _, sql: _query(name, sql))
                comparison = reconcile(source_lineage, lineage)
            except LineageError:
                raise IndependentRestoreError("independent PostgreSQL lineage mismatch") from None

            document_sql = (
                "SELECT COALESCE(json_agg(json_build_object("
                "'key', d.storage_key, 'sha256', d.file_hash, 'size', d.file_size_bytes"
                ") ORDER BY d.storage_key)::text, '[]') "
                "FROM documents d JOIN claims c ON c.id=d.claim_id "
                "WHERE c.external_reference='MCRI-DEMO-MT-ORION';"
            )
            with tempfile.TemporaryDirectory(prefix="mcri-ci-second-evidence-") as restored:
                try:
                    evidence = restore_and_reconcile(
                        archive, Path(restored), _query(name, document_sql))
                except EvidenceRestoreError:
                    raise IndependentRestoreError("independent PostgreSQL Evidence mismatch") from None
            if evidence["demo_documents_matched"] < 1:
                raise IndependentRestoreError("no synthetic Documents reconciled independently")
            return {
                "separate_postgres_engine_restored": True,
                "isolated_container_network_disabled": True,
                "separate_engine_claim_count_and_migration_matched": True,
                "separate_engine_lineage_families_matched": comparison["lineage_families_compared"],
                "separate_engine_lineage_rows_matched": comparison["lineage_rows_compared"],
                "separate_engine_documents_matched": evidence["demo_documents_matched"],
                "real_fresh_host_recovery_verified": False,
                "pilot_authorized": False,
            }
        finally:
            if started:
                # Destroy ONLY the container we launched; -v removes its
                # anonymous data volume. If teardown fails, CI must fail.
                _run(["docker", "rm", "-f", "-v", name], timeout=60)
