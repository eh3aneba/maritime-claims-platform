from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
import stat
import subprocess
import sys
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore_postgres.sh"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from pilot_recovery_pair import observe  # noqa: E402


def _fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
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

if [[ "${*:-}" == "ps --status running --services" && "${1:-}" == "ps" ]]; then
  printf '%b' "${FAKE_RUNNING_SERVICES:-db\\nclamav\\n}"
  exit 0
fi

if [[ " ${*:-} " == *" pg_restore --list "* ]]; then
  cat >/dev/null
  if [[ "${FAKE_ARCHIVE_INVALID:-0}" == "1" ]]; then
    exit 42
  fi
fi
if [[ " ${*:-} " == *" pg_restore "* ]]; then
  cat >/dev/null
fi

exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return fake_bin, log_path


def _run_restore(
    tmp_path: Path,
    *,
    confirmed: bool = True,
    running_services: str = "db\\nclamav\\n",
    app_env: str = "development",
    with_pair: bool = False,
    tamper_dump: bool = False,
    tamper_evidence: bool = False,
    missing_metadata: bool = False,
    wrong_database: bool = False,
    invalid_archive: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    dump = tmp_path / "backup.dump"
    dump.write_bytes(b"fake-custom-format-dump")
    sha = hashlib.sha256(dump.read_bytes()).hexdigest()
    Path(str(dump) + ".sha256").write_text(
        f"{sha}  {dump.name}\\n", encoding="utf-8"
    )
    Path(str(dump) + ".meta").write_text(
        "format=mcri-postgres-backup-v1\\n"
        "created_at_utc=2026-10-10T03:00:00Z\\n"
        f"database={'not-the-target' if wrong_database else 'maritime_claims'}\\n"
        f"git_sha={'a' * 40}\\n"
        "alembic_heads=0224_obs_refresh_recovery_anchor\\n"
        f"dump_file={dump.name}\\n"
        f"dump_sha256={sha}\\n",
        encoding="utf-8",
    )
    fake_bin, log_path = _fake_docker(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log_path)
    env["FAKE_RUNNING_SERVICES"] = running_services
    env["APP_ENV"] = app_env
    env["POSTGRES_DB"] = "maritime_claims"
    env.pop("MCRI_RESTORE_PAIR_MANIFEST", None)
    env.pop("MCRI_RESTORE_EVIDENCE_ARCHIVE", None)
    env.pop("MCRI_RESTORE_RELEASE_SHA", None)
    if invalid_archive:
        env["FAKE_ARCHIVE_INVALID"] = "1"
    else:
        env.pop("FAKE_ARCHIVE_INVALID", None)
    if confirmed:
        env["MCRI_RESTORE_CONFIRM"] = "YES"
    else:
        env.pop("MCRI_RESTORE_CONFIRM", None)

    if with_pair:
        archive = tmp_path / "evidence.tar"
        with tarfile.open(archive, mode="w") as tf:
            data = b"synthetic-only-evidence"
            item = tarfile.TarInfo("documents/synthetic.txt")
            item.size = len(data)
            tf.addfile(item, BytesIO(data))
        record = observe(
            db_dump=dump, evidence_archive=archive,
            release_sha="a" * 40, quiescence_ref="test-recovery-001",
        )
        manifest = tmp_path / "pair.json"
        manifest.write_text(json.dumps(record), encoding="utf-8")
        env["MCRI_RESTORE_PAIR_MANIFEST"] = str(manifest)
        env["MCRI_RESTORE_EVIDENCE_ARCHIVE"] = str(archive)
        env["MCRI_RESTORE_RELEASE_SHA"] = "a" * 40
        if tamper_evidence:
            archive.write_bytes(archive.read_bytes() + b"tampered")
    if tamper_dump:
        dump.write_bytes(dump.read_bytes() + b"tampered")
    if missing_metadata:
        Path(str(dump) + ".meta").unlink()

    result = subprocess.run(
        ["bash", str(RESTORE_SCRIPT), str(dump)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return result, log


def test_restore_quiesces_all_current_application_services(tmp_path: Path) -> None:
    result, log = _run_restore(tmp_path)

    assert result.returncode == 0, result.stderr
    stop_line = next(line for line in log.splitlines() if line.startswith("compose stop "))
    for service in (
        "web",
        "api",
        "worker",
        "governance-webhook-worker",
        "external-evidence-scheduler-worker",
        "external-evidence-observation-worker",
        "external-evidence-review-projector-worker",
        "demo-seed",
        "preflight",
        "migrate",
    ):
        assert service in stop_line
    assert " db" not in stop_line
    assert " clamav" not in stop_line
    assert "compose exec -T db dropdb" in log
    assert "compose run --rm migrate" in log
    assert "compose run --rm preflight" in log


def test_restore_fails_closed_if_unknown_service_is_still_running(tmp_path: Path) -> None:
    result, log = _run_restore(
        tmp_path,
        running_services="db\nclamav\nfuture-db-writer\n",
    )

    assert result.returncode != 0
    assert "unexpected Compose services are still running" in result.stderr
    assert "future-db-writer" in result.stderr
    assert "dropdb" not in log


def test_restore_requires_explicit_destructive_confirmation(tmp_path: Path) -> None:
    result, log = _run_restore(tmp_path, confirmed=False)

    assert result.returncode != 0
    assert "Refusing destructive restore" in result.stderr
    assert log == ""

def test_restore_verifies_backup_before_dropdb(tmp_path: Path) -> None:
    result, log = _run_restore(tmp_path)

    assert result.returncode == 0, result.stderr
    assert log.index("compose exec -T db pg_restore --list") < log.index(
        "compose exec -T db dropdb"
    )
    assert "Backup verification passed" in result.stdout


def test_corrupt_or_incomplete_backup_never_reaches_dropdb(tmp_path: Path) -> None:
    for name, changes in (
        ("tampered", {"tamper_dump": True}),
        ("no-metadata", {"missing_metadata": True}),
        ("wrong-database", {"wrong_database": True}),
        ("bad-archive", {"invalid_archive": True}),
    ):
        case = tmp_path / name
        case.mkdir()
        result, log = _run_restore(case, **changes)
        assert result.returncode != 0, (name, result.stderr)
        assert "dropdb" not in log, name
        assert "createdb" not in log, name
        assert "compose run --rm migrate" not in log, name


def test_private_pilot_requires_evidence_pair_before_restore(tmp_path: Path) -> None:
    result, log = _run_restore(tmp_path, app_env="pilot")
    assert result.returncode != 0
    assert "without DB/Evidence integrity pairing" in result.stderr
    assert log == ""


def test_private_pilot_pair_is_verified_before_dropdb(tmp_path: Path) -> None:
    result, log = _run_restore(tmp_path, app_env="pilot", with_pair=True)
    assert result.returncode == 0, result.stderr
    assert "RECOVERY ARTIFACT DIGESTS VERIFIED" in result.stdout
    assert "compose exec -T db dropdb" in log


def test_mutated_evidence_archive_blocks_destructive_pilot_restore(tmp_path: Path) -> None:
    result, log = _run_restore(
        tmp_path, app_env="pilot", with_pair=True, tamper_evidence=True,
    )
    assert result.returncode != 0
    assert "NO-GO" in result.stderr
    assert "dropdb" not in log

def test_missing_environment_classification_refuses_destructive_restore(tmp_path: Path) -> None:
    result, log = _run_restore(tmp_path, app_env="")
    assert result.returncode != 0
    assert "recognized explicit APP_ENV" in result.stderr
    assert log == ""


def test_staging_and_production_refuse_unpaired_restore(tmp_path: Path) -> None:
    for mode in ("staging", "production"):
        case = tmp_path / mode
        case.mkdir()
        result, log = _run_restore(case, app_env=mode)
        assert result.returncode != 0
        assert "without DB/Evidence integrity pairing" in result.stderr
        assert log == ""
