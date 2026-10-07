from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_postgres.sh"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_postgres_backup.sh"


def _fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    log_path = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s' "$1" >> "$FAKE_DOCKER_LOG"
shift || true
for arg in "$@"; do
  printf ' %s' "$arg" >> "$FAKE_DOCKER_LOG"
done
printf '\n' >> "$FAKE_DOCKER_LOG"

if [[ " ${*:-} " == *" pg_dump "* ]]; then
  printf 'fake-postgres-custom-format-dump'
  exit 0
fi

if [[ " ${*:-} " == *" pg_restore --list "* ]]; then
  cat >/dev/null
  if [[ "${FAKE_PG_RESTORE_FAIL:-0}" == "1" ]]; then
    exit 42
  fi
  exit 0
fi

if [[ " ${*:-} " == *" psql "* ]]; then
  count=0
  if [[ -f "$FAKE_PSQL_COUNT_FILE" ]]; then
    count="$(cat "$FAKE_PSQL_COUNT_FILE")"
  fi
  count=$((count + 1))
  printf '%s' "$count" > "$FAKE_PSQL_COUNT_FILE"
  if [[ "$count" -gt 1 && -n "${FAKE_ALEMBIC_HEAD_SECOND:-}" ]]; then
    printf '%s\n' "$FAKE_ALEMBIC_HEAD_SECOND"
  else
    printf '%s\n' "${FAKE_ALEMBIC_HEAD_FIRST:-0224_obs_refresh_recovery_anchor}"
  fi
  exit 0
fi

exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return fake_bin, log_path


def _run_backup(
    tmp_path: Path,
    *,
    archive_validation_fails: bool = False,
    alembic_head_second: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    output = tmp_path / "pilot.dump"
    fake_bin, log_path = _fake_docker(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log_path)
    env["FAKE_PSQL_COUNT_FILE"] = str(tmp_path / "psql-count")
    if archive_validation_fails:
        env["FAKE_PG_RESTORE_FAIL"] = "1"
    if alembic_head_second is not None:
        env["FAKE_ALEMBIC_HEAD_SECOND"] = alembic_head_second

    result = subprocess.run(
        ["bash", str(BACKUP_SCRIPT), str(output)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return result, output, log



def _run_verify(
    tmp_path: Path,
    output: Path,
) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin, log_path = _fake_docker(tmp_path / "verify")
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log_path)
    env["FAKE_PSQL_COUNT_FILE"] = str(tmp_path / "verify-psql-count")

    result = subprocess.run(
        ["bash", str(VERIFY_SCRIPT), str(output)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return result, log

def test_backup_is_validated_hashed_and_published_atomically(tmp_path: Path) -> None:
    result, output, log = _run_backup(tmp_path)

    assert result.returncode == 0, result.stderr
    expected_bytes = b"fake-postgres-custom-format-dump"
    assert output.read_bytes() == expected_bytes

    digest = hashlib.sha256(expected_bytes).hexdigest()
    checksum = Path(f"{output}.sha256").read_text(encoding="utf-8")
    metadata = Path(f"{output}.meta").read_text(encoding="utf-8")

    assert checksum == f"{digest}  {output.name}\n"
    assert "format=mcri-postgres-backup-v1" in metadata
    assert "alembic_heads=0224_obs_refresh_recovery_anchor" in metadata
    assert f"dump_file={output.name}" in metadata
    assert f"dump_sha256={digest}" in metadata
    assert "compose exec -T db pg_dump" in log
    assert "compose exec -T db pg_restore --list" in log
    assert log.count("compose exec -T db psql") == 2
    assert not list(tmp_path.glob("*.partial.*"))

    verified, verify_log = _run_verify(tmp_path, output)
    assert verified.returncode == 0, verified.stderr
    assert "Backup verification passed" in verified.stdout
    assert "compose exec -T db pg_restore --list" in verify_log



def test_backup_verifier_rejects_tampered_dump(tmp_path: Path) -> None:
    result, output, _ = _run_backup(tmp_path)
    assert result.returncode == 0, result.stderr

    output.write_bytes(output.read_bytes() + b"-tampered")
    verified, verify_log = _run_verify(tmp_path, output)

    assert verified.returncode != 0
    assert "Backup checksum mismatch" in verified.stderr
    assert "pg_restore --list" not in verify_log

def test_backup_archive_validation_failure_publishes_nothing(tmp_path: Path) -> None:
    result, output, _ = _run_backup(tmp_path, archive_validation_fails=True)

    assert result.returncode != 0
    assert "Backup archive validation failed" in result.stderr
    assert not output.exists()
    assert not Path(f"{output}.sha256").exists()
    assert not Path(f"{output}.meta").exists()
    assert not list(tmp_path.glob("*.partial.*"))


def test_backup_rejects_alembic_revision_drift(tmp_path: Path) -> None:
    result, output, _ = _run_backup(
        tmp_path,
        alembic_head_second="0225_changed_during_backup",
    )

    assert result.returncode != 0
    assert "Alembic revision changed during backup" in result.stderr
    assert not output.exists()
    assert not Path(f"{output}.sha256").exists()
    assert not Path(f"{output}.meta").exists()
    assert not list(tmp_path.glob("*.partial.*"))


def test_backup_refuses_to_overwrite_existing_artifact(tmp_path: Path) -> None:
    output = tmp_path / "pilot.dump"
    output.write_bytes(b"preserve-me")
    fake_bin, log_path = _fake_docker(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log_path)
    env["FAKE_PSQL_COUNT_FILE"] = str(tmp_path / "psql-count")

    result = subprocess.run(
        ["bash", str(BACKUP_SCRIPT), str(output)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Refusing to overwrite existing backup artifact" in result.stderr
    assert output.read_bytes() == b"preserve-me"
    assert not log_path.exists() or log_path.read_text(encoding="utf-8") == ""
