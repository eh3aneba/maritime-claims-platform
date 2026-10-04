from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore_postgres.sh"


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
    running_services: str = "db\nclamav\n",
) -> tuple[subprocess.CompletedProcess[str], str]:
    dump = tmp_path / "backup.dump"
    dump.write_bytes(b"fake-custom-format-dump")
    fake_bin, log_path = _fake_docker(tmp_path)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_LOG"] = str(log_path)
    env["FAKE_RUNNING_SERVICES"] = running_services
    if confirmed:
        env["MCRI_RESTORE_CONFIRM"] = "YES"
    else:
        env.pop("MCRI_RESTORE_CONFIRM", None)

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
