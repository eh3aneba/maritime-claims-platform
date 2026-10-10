#!/usr/bin/env python3
"""Fail-closed Pilot operations monitoring ownership/alert coverage record.

Records are operator-entered attestations, not monitoring probes. The helper
does NOT query production systems, verify a person's identity, trigger alerts,
call an on-call service, or authorize Pilot/customer traffic.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

SCHEMA = "mcri-pilot-monitoring-ownership-v1"
SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
REF_RE = re.compile(r"(?:monitor|runbook|artifact|ticket)://[A-Za-z0-9._:/-]{3,200}\Z")
IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@:/-]{2,79}\Z")
SIGNALS = (
    "api_liveness_and_readiness",
    "postgres_connectivity_and_migration",
    "document_worker_and_queue",
    "external_evidence_scheduler_worker",
    "external_evidence_observation_worker",
    "external_evidence_review_projector_worker",
    "evidence_storage_health_and_capacity",
    "clamav_scanner_health",
    "backup_age_and_recovery_readiness",
    "authentication_failure_signal",
    "bounded_pilot_error_and_latency",
)
ALERT_SEVERITIES = frozenset(("p0", "p1", "p2", "p3"))


class MonitoringRecordError(ValueError):
    """No raw operator-controlled content is included in validation errors."""


def draft(sha: str) -> dict:
    if not SHA_RE.fullmatch(sha):
        raise MonitoringRecordError("exact lowercase release SHA required")
    return {
        "schema": SCHEMA,
        "release_sha": sha,
        "environment_ref": "",
        "signals": {
            key: {
                "status": "pending",
                "owner_role": "",
                "escalation_role": "",
                "severity": "",
                "cadence_minutes": None,
                "response_minutes": None,
                "alert_rule_ref": "",
                "exercise_evidence_ref": "",
                "exercised_at_utc": "",
            }
            for key in SIGNALS
        },
    }


def _utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (parsed.tzinfo == timezone.utc
            and parsed.isoformat(timespec="seconds").endswith("+00:00")
            and parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value)


def check(record: object, *, expected_sha: str) -> dict[str, int | bool]:
    if not SHA_RE.fullmatch(expected_sha):
        raise MonitoringRecordError("invalid independently supplied release SHA")
    if not isinstance(record, dict) or set(record) != {
        "schema", "release_sha", "environment_ref", "signals",
    }:
        raise MonitoringRecordError("monitoring record schema incomplete")
    if record["schema"] != SCHEMA or record["release_sha"] != expected_sha:
        raise MonitoringRecordError("monitoring release identity mismatch")
    if not isinstance(record["environment_ref"], str) or not REF_RE.fullmatch(
        record["environment_ref"]
    ):
        raise MonitoringRecordError("monitoring environment reference missing or invalid")
    signals = record["signals"]
    if not isinstance(signals, dict) or set(signals) != set(SIGNALS):
        raise MonitoringRecordError("monitoring signal coverage incomplete")
    for key in SIGNALS:
        entry = signals[key]
        if not isinstance(entry, dict) or set(entry) != {
            "status", "owner_role", "escalation_role", "severity",
            "cadence_minutes", "response_minutes", "alert_rule_ref",
            "exercise_evidence_ref", "exercised_at_utc",
        }:
            raise MonitoringRecordError("monitoring signal entry incomplete")
        if entry["status"] != "verified":
            raise MonitoringRecordError("monitoring signal not independently verified")
        for label in ("owner_role", "escalation_role"):
            if not isinstance(entry[label], str) or not IDENTITY_RE.fullmatch(entry[label]):
                raise MonitoringRecordError("monitoring ownership or escalation missing")
        if not isinstance(entry["severity"], str) or entry["severity"] not in ALERT_SEVERITIES:
            raise MonitoringRecordError("monitoring severity missing or invalid")
        for label in ("cadence_minutes", "response_minutes"):
            value = entry[label]
            if type(value) is not int or not 1 <= value <= 1440:
                raise MonitoringRecordError("monitoring cadence or response bound invalid")
        for label in ("alert_rule_ref", "exercise_evidence_ref"):
            value = entry[label]
            if not isinstance(value, str) or not REF_RE.fullmatch(value):
                raise MonitoringRecordError("monitoring rule or alert exercise proof missing")
        if not _utc(entry["exercised_at_utc"]):
            raise MonitoringRecordError("monitoring test UTC timestamp missing or invalid")
    return {
        "required_signals": len(SIGNALS),
        "verified_signal_records": len(SIGNALS),
        "monitoring_runtime_confirmed": False,
        "alert_delivery_confirmed": False,
        "owner_independently_confirmed": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="mode", required=True)
    start = subs.add_parser("init")
    start.add_argument("--sha", required=True)
    start.add_argument("--output", required=True, type=Path)
    verify = subs.add_parser("check")
    verify.add_argument("record", type=Path)
    verify.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    if args.mode == "init":
        try:
            record = draft(args.sha)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2, sort_keys=True)
                stream.write("\n")
        except MonitoringRecordError as exc:
            print(f"NO-GO: {exc}", file=sys.stderr)
            return 2
        except OSError:
            print("NO-GO: cannot create exclusive monitoring draft", file=sys.stderr)
            return 2
        print("NO-GO monitoring ownership draft created; no alerts tested.")
        return 0
    try:
        with args.record.open(encoding="utf-8") as stream:
            raw = json.load(stream)
        result = check(raw, expected_sha=args.expected_sha)
    except MonitoringRecordError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("NO-GO: monitoring ownership record unreadable", file=sys.stderr)
        return 2
    print(f"MONITORING RECORD COMPLETE: {result['verified_signal_records']} signal attestations.")
    print("Real alert delivery, named operator acceptance and Pilot GO NOT established.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
