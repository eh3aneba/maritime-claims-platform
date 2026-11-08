"""One-time, isolated Debian Slim SQLite feasibility observation.

Diagnostic only: NOT a CVE adjudication, clean final-image scan or permission
to change the production Dockerfile. No customer data or foreign AI services.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

IMAGE = "python:3.14.10-slim-trixie"
EXPECTED_FIELDS = {"sqlite_version", "debian_sqlite_package", "sqlite_cli_present", "fts5_synthetic_ok"}
PYTHON_PROBE = r"""
import json, shutil, sqlite3, subprocess
db = sqlite3.connect(":memory:")
db.execute("CREATE VIRTUAL TABLE probe USING fts5(term)")
db.execute("INSERT INTO probe(term) VALUES (?)", ("synthetic",))
fts5_ok = db.execute("SELECT count(*) FROM probe WHERE probe MATCH 'synthetic'").fetchone()[0] == 1
pkg = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "libsqlite3-0"],
                     check=True, capture_output=True, text=True).stdout.strip()
print(json.dumps({"sqlite_version": sqlite3.sqlite_version,
                  "debian_sqlite_package": pkg,
                  "sqlite_cli_present": shutil.which("sqlite3") is not None,
                  "fts5_synthetic_ok": fts5_ok}, sort_keys=True))
"""


class ProbeError(RuntimeError):
    pass


def validate(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != EXPECTED_FIELDS:
        raise ProbeError("Incomplete/ambiguous Debian SQLite observation")
    if not isinstance(data["sqlite_version"], str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", data["sqlite_version"]
    ):
        raise ProbeError("Invalid SQLite runtime version")
    if not isinstance(data["debian_sqlite_package"], str) or not re.fullmatch(
        r"[A-Za-z0-9.+:~_-]{1,90}", data["debian_sqlite_package"]
    ):
        raise ProbeError("Invalid Debian package version")
    if type(data["sqlite_cli_present"]) is not bool or type(data["fts5_synthetic_ok"]) is not bool:
        raise ProbeError("Invalid SQLite feature/probe flags")
    if not data["fts5_synthetic_ok"]:
        raise ProbeError("Synthetic FTS5 compatibility check failed")
    return data


def report(data: dict, image_digest: str) -> str:
    data = validate(data)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ProbeError("Missing/invalid exact image digest")
    version = tuple(int(p) for p in data["sqlite_version"].split("."))
    preliminary = (
        "Below upstream 3.54.0 library-fix baseline; distro backports must be assessed separately."
        if version < (3, 54, 0)
        else "At/above upstream library-fix baseline; CLI CVE and distribution status still unverified."
    )
    return "\n".join([
        "### Debian Slim SQLite feasibility — diagnostic ONLY",
        "",
        "**NO-GO: not approved as a security remediation or a production base-image change.**",
        f"- Base image: `{IMAGE}` (observed digest `{image_digest}`).",
        f"- Python-linked SQLite: `{data['sqlite_version']}`.",
        f"- Debian libsqlite3-0 package: `{data['debian_sqlite_package']}`.",
        f"- sqlite3 CLI present: `{str(data['sqlite_cli_present']).lower()}`.",
        f"- Synthetic in-memory FTS5 check: `{str(data['fts5_synthetic_ok']).lower()}`.",
        f"- Version interpretation: {preliminary}",
        "- Reference: https://security-tracker.debian.org/tracker/source-package/sqlite3",
        "- A distro backport may fix a CVE without changing the upstream version.",
        "- CLI absence is **not** Grype clearance or an authorized CVE/VEX exception.",
        "- No final API/Worker image was built or scanned; OCR/PDF signing/ABI are untested.",
        "- To change production: independently approved supported/signed source, clean final",
        "  API + Worker + Web Grype High scans, real OCR/PG/backend tests, and all 11 checks.",
        "- The production Alpine images and every existing security gate are unchanged.",
        "",
    ]) + "\n"


def call(args: list[str], timeout: int) -> str:
    try:
        result = subprocess.run(args, check=True, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProbeError("Bounded diagnostic Docker command failed (no remediation inferred)") from exc
    return result.stdout.strip()


def main() -> int:
    try:
        call(["docker", "pull", IMAGE], 180)
        digest = call(
            ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", IMAGE], 30
        ).rsplit("@", 1)[-1]
        raw = call(
            ["docker", "run", "--rm", "--network=none", "--read-only",
             "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64",
             "--memory=256m", IMAGE, "python", "-B", "-c", PYTHON_PROBE], 60
        )
        summary = report(json.loads(raw), digest)
    except (ProbeError, ValueError, json.JSONDecodeError) as exc:
        print(f"INCONCLUSIVE: {exc}", file=sys.stderr)
        return 2
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary)
    return 0  # Successful evidence collection, NEVER a green image vulnerability scan.


if __name__ == "__main__":
    raise SystemExit(main())
