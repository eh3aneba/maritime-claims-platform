#!/usr/bin/env python3
"""Fail-closed synthetic-only real ClamAV boundary proof for Pilot CI.

Read-only to the real claims database and evidence store. Runs ephemeral
synthetic clean/EICAR files inside the existing API container via stdin,
without persisting contents to CI artifacts or emitting scanner responses.
No actual customer data, real malware or production Pilot authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

SHA_RE = re.compile(r"[a-f0-9]{40}\\Z")

# Passed via stdin to the existing synthetic CI API container; no need to
# ship an acceptance harness in the production API image.
_IN_CONTAINER = r"""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

try:
    from app.modules.documents.malware import (
        MalwareScanVerdict, ping_clamd, scan_file,
    )
    if os.environ.get("APP_ENV") != "test":
        raise RuntimeError("not synthetic test environment")
    if os.environ.get("MALWARE_SCAN_ENABLED", "").lower() != "true":
        raise RuntimeError("malware scan not explicitly enabled")
    host = os.environ.get("CLAMAV_HOST", "clamav")
    if host != "clamav":
        raise RuntimeError("unexpected scanner endpoint")
    port = int(os.environ.get("CLAMAV_PORT", "3310"))
    if port != 3310:
        raise RuntimeError("unexpected scanner port")
    ping_clamd(host=host, port=port, timeout_seconds=20)
    with TemporaryDirectory(prefix="mcri-synthetic-clamav-") as location:
        path = Path(location) / "synthetic.bin"
        path.write_bytes(b"MCRI harmless synthetic scanner acceptance sample.")
        clean = scan_file(path, host=host, port=port, timeout_seconds=20)
        # Harmless EICAR test signature, not a virus or customer document.
        eicar = b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
        if len(eicar) != 68:
            raise RuntimeError("synthetic fixture malformed")
        path.write_bytes(eicar)
        flagged = scan_file(path, host=host, port=port, timeout_seconds=20)
    if clean.verdict != MalwareScanVerdict.CLEAN:
        raise RuntimeError("synthetic clean-file rejection")
    if flagged.verdict != MalwareScanVerdict.INFECTED:
        raise RuntimeError("synthetic EICAR was not rejected")
    print(json.dumps({"schema":"mcri-ci-clamav-test-v1",
                      "ping":"pass","clean":"pass","eicar_detected":"pass"}))
except Exception:
    # Scanner exceptions can include raw socket/server paths; never log them.
    print('{"schema":"mcri-ci-clamav-test-v1","result":"fail"}')
    sys.exit(1)
"""


class ProbeError(RuntimeError):
    """A safe fixed-classification error; never contains raw Compose output."""


def evaluate(raw: str, *, returncode: int, release_sha: str) -> dict:
    if not SHA_RE.fullmatch(release_sha):
        raise ProbeError("invalid exact candidate SHA")
    if returncode != 0:
        raise ProbeError("synthetic live ClamAV scan check failed")
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        raise ProbeError("malformed synthetic ClamAV response") from None
    if not isinstance(result, dict) or result != {
        "schema": "mcri-ci-clamav-test-v1",
        "ping": "pass",
        "clean": "pass",
        "eicar_detected": "pass",
    }:
        raise ProbeError("synthetic ClamAV scan checks incomplete")
    return {
        "schema": "mcri-pilot-clamav-evidence-v1",
        "operator_supplied_release_sha": release_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "environment": "synthetic_ci_only",
        "daemon_ping": "pass",
        "synthetic_clean_scan": "pass",
        "synthetic_eicar_rejected": "pass",
        "scanner_runtime_behavior_observed": True,
        "production_scanner_attested": False,
        "customer_evidence_verified": False,
        "operator_approved": False,
        "pilot_authorized": False,
    }


def observe(*, env_file: str, timeout: int = 90) -> tuple[str, int]:
    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", env_file,
             "exec", "-T", "api", "python", "-"],
            input=_IN_CONTAINER, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeError("synthetic live ClamAV observation unavailable") from None
    return result.stdout, result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not SHA_RE.fullmatch(args.release_sha):
            raise ProbeError("invalid exact candidate SHA")
        raw, returncode = observe(env_file=args.env_file)
        record = evaluate(raw, returncode=returncode, release_sha=args.release_sha)
        with args.output.open("x", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\\n")
    except ProbeError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive synthetic scan evidence", file=sys.stderr)
        return 2
    print("SYNTHETIC CLAMAV CHECK PASS: clean accepted; EICAR detected.")
    print("This is NOT production scanner approval or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
