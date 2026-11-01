"""Read-only synthetic ClamAV VERSION/age observation; no freshness policy."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import sys

SHA = re.compile(r"[a-f0-9]{40}\Z")
VERSION = re.compile(r"ClamAV ([0-9]+\.[0-9]+\.[0-9]+)/([0-9]{1,10})/(.{1,40})\Z")


def evaluate(raw: str, *, observed_at: datetime, release_sha: str,
             signature_timezone: str | None) -> dict:
    if not SHA.fullmatch(release_sha) or observed_at.utcoffset() is None:
        raise ValueError("invalid_observation_identity_or_clock")
    if signature_timezone not in (None, "UTC"):
        raise ValueError("unsupported_declared_signature_timezone")
    observed_at = observed_at.astimezone(timezone.utc)
    record = {
        "schema": "mcri-clamav-signature-observation-v1",
        "operator_supplied_release_sha": release_sha,
        "observed_at_utc": observed_at.isoformat(),
        "engine_version": None,
        "signature_database_serial": None,
        "signature_timestamp_utc": None,
        "signature_timezone_declared": signature_timezone,
        "signature_timezone_independently_verified": False,
        "signature_age_seconds_signed": None,
        "observation_state": "unavailable_or_malformed",
        "freshness_policy_evaluated": False,
        "acceptable_freshness_threshold_defined": False,
        "customer_admission_policy_changed": False,
        "scanner_release_binding_verified": False,
        "signature_authenticity_verified": False,
        "current_malware_coverage_verified": False,
        "production_scanner_attested": False,
        "pilot_authorized": False,
    }
    if not isinstance(raw, str) or len(raw) > 256:
        return record
    match = VERSION.fullmatch(raw)
    if match is None:
        return record
    try:
        timestamp = datetime.strptime(match[3], "%a %b %d %H:%M:%S %Y")
        if timestamp.strftime("%a") != match[3][:3] or int(match[2]) < 1:
            return record
    except ValueError:
        return record
    record.update(engine_version=match[1], signature_database_serial=int(match[2]))
    if signature_timezone is None:
        record["observation_state"] = "signature_timezone_unresolved"
        return record
    # VERSION has no UTC offset. Never silently use the observer host timezone.
    # The operator declares the daemon timestamp's timezone; this is not attestation.
    timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = int((observed_at - timestamp).total_seconds())
    record.update(
        signature_timestamp_utc=timestamp.isoformat(),
        signature_age_seconds_signed=age,
        observation_state="future_dated" if timestamp > observed_at else "metadata_observed",
    )
    return record


def observe_version(*, port: int, timeout: float = 5) -> str:
    if port not in (3310, 13310):
        raise ValueError("unsupported_synthetic_scanner_port")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(b"zVERSION\0")
        data = bytearray()
        while len(data) < 257:
            chunk = connection.recv(257 - len(data))
            if not chunk:
                raise ValueError("unterminated_scanner_metadata")
            data.extend(chunk)
            if b"\0" in chunk:
                value, extra = bytes(data).split(b"\0", 1)
                if extra or len(value) > 256:
                    raise ValueError("invalid_scanner_metadata_frame")
                return value.decode("ascii")
        raise ValueError("scanner_metadata_too_long")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--signature-timezone", choices=("UTC",), default=None)
    parser.add_argument("--port", type=int, choices=(3310, 13310), default=13310)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("MCRI_SYNTHETIC_ONLY_CONFIRM") != "YES"
            or not SHA.fullmatch(args.release_sha)):
        print("synthetic_scanner_observation_guard_rejected", file=sys.stderr)
        return 2
    try:
        try:
            raw = observe_version(port=args.port)
        except (OSError, ValueError, UnicodeError):
            raw = ""
        record = evaluate(raw, observed_at=datetime.now(timezone.utc),
                          release_sha=args.release_sha,
                          signature_timezone=args.signature_timezone)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(record, output, indent=2, sort_keys=True)
            output.write("\n")
    except (OSError, ValueError):
        print("scanner_observation_record_unavailable", file=sys.stderr)
        return 2
    print("Scanner metadata observation only; no freshness or admission approval.")
    return 0 if record["observation_state"] == "metadata_observed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
