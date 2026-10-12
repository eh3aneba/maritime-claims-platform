#!/usr/bin/env python3
"""Fail closed if an opt-in real OpenSSH acceptance suite did not run its tests.

The raw pytest JUnit report remains private to the ephemeral CI runner. This
script prints only a bounded suite name and count: no XML, filenames, tracebacks,
tokens, fixture bytes or assertion messages are included in artifacts.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

REQUIRED_CASES = {
    "live_runtime": frozenset((
        "test_real_openssh_positive_path_uses_production_runtime",
        "test_real_openssh_wrong_pin_and_bad_password_fail_closed",
        "test_real_openssh_missing_traversal_symlink_and_oversize_are_rejected",
        "test_real_tcp_peer_abrupt_disconnect_before_ssh_banner_fails_closed",
        "test_real_tcp_peer_ssh_banner_stall_has_bounded_failure",
        "test_real_openssh_authenticated_partial_read_transport_drop_discards_all_bytes",
        "test_real_openssh_same_size_inplace_rewrite_during_read_fails_closed",
        "test_real_openssh_unavailable_port_fails_closed_without_authentication",
        "test_real_openssh_permission_denied_read_fails_closed",
        "test_real_openssh_sftp_principal_cannot_write_rename_delete_or_mkdir",
    )),
    "postgres_due_tick": frozenset((
        "test_real_openssh_stat_persists_changed_observation_and_replays_without_io",
        "test_real_openssh_missing_file_stays_missing_on_postgres_replay",
    )),
    "governed_nplus1": frozenset((
        "test_real_openssh_changed_read_then_human_authorized_nplus1_and_next_unchanged",
    )),
    "initial_custody": frozenset((
        "test_real_openssh_initial_list_content_proof_quarantine_checkpoint",
    )),
}
MAX_REPORT_BYTES = 1024 * 1024


class VerificationError(ValueError):
    """Sanitized acceptance outcome only (never relay raw source data)."""


def verify_report(*, suite: str, report_bytes: bytes) -> int:
    if suite not in REQUIRED_CASES:
        raise VerificationError("unknown acceptance suite")
    if not report_bytes or len(report_bytes) > MAX_REPORT_BYTES:
        raise VerificationError("missing or oversized JUnit result")
    if b"<!DOCTYPE" in report_bytes.upper() or b"<!ENTITY" in report_bytes.upper():
        raise VerificationError("unsafe JUnit format")
    try:
        root = ET.fromstring(report_bytes)
    except ET.ParseError as exc:
        raise VerificationError("unreadable JUnit XML") from exc
    if root.tag not in {"testsuites", "testsuite"}:
        raise VerificationError("unexpected JUnit root")

    cases = root.findall(".//testcase")
    if not cases:
        raise VerificationError("no tests executed")
    for testcase in cases:
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            raise VerificationError("failed or errored acceptance test")
        if testcase.find("skipped") is not None:
            raise VerificationError("skipped acceptance test")
        if testcase.get("name") is None:
            raise VerificationError("unnamed acceptance test")
    for suite_node in [root] + root.findall(".//testsuite"):
        for field in ("tests", "failures", "errors", "skipped"):
            raw = suite_node.get(field)
            if raw is None:
                continue
            if not raw.isdecimal():
                raise VerificationError("malformed JUnit totals")
            count = int(raw)
            if field == "tests" and count != len(cases):
                raise VerificationError("JUnit declared test count mismatch")
            if field != "tests" and count != 0:
                raise VerificationError("JUnit reports unsuccessful tests")

    observed: dict[str, int] = {}
    for case in cases:
        name = case.get("name", "").split("[", 1)[0]
        observed[name] = observed.get(name, 0) + 1
    if any(observed.get(name, 0) != 1 for name in REQUIRED_CASES[suite]):
        raise VerificationError("required real SFTP test missing or duplicated")
    return len(cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(REQUIRED_CASES), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.report.is_file():
            raise VerificationError("JUnit result not present")
        # Do not use read_text or dump the XML, even on a CI failure.
        if args.report.stat().st_size > MAX_REPORT_BYTES:
            raise VerificationError("oversized JUnit result")
        count = verify_report(
            suite=args.suite, report_bytes=args.report.read_bytes(),
        )
    except (VerificationError, OSError) as exc:
        # Never forward filesystem exception messages or raw XML; they may
        # contain runner paths or test fixture metadata.
        _ = exc
        print("NO-GO: real SFTP JUnit coverage verification failed", file=sys.stderr)
        return 2
    print(
        f"Real SFTP {args.suite}: {count} executed tests, "
        "all required names present; no skip/fail/error. NOT a Pilot GO."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
