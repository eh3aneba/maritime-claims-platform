"""Offline regressions for exact-SHA Pilot monitoring coverage/owner record."""
from copy import deepcopy
import contextlib
import io
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_monitoring_ownership as m  # noqa: E402

SHA = "a" * 40
STAMP = "2026-10-10T17:30:00Z"


def complete() -> dict:
    data = m.draft(SHA)
    data["environment_ref"] = "runbook://synthetic-ci-monitoring"
    for signal, row in data["signals"].items():
        row.update({
            "status": "verified",
            "owner_role": "ops-primary",
            "escalation_role": "ops-secondary",
            "severity": "p1",
            "cadence_minutes": 5,
            "response_minutes": 30,
            "alert_rule_ref": "monitor://synthetic-rule-" + signal,
            "exercise_evidence_ref": "artifact://synthetic-exercise-" + signal,
            "exercised_at_utc": STAMP,
        })
    return data


class MonitoringCoverageTests(unittest.TestCase):
    def test_empty_draft_never_passes(self):
        obj = m.draft(SHA)
        self.assertEqual(len(obj["signals"]), 11)
        self.assertTrue(all(r["status"] == "pending" for r in obj["signals"].values()))
        with self.assertRaises(m.MonitoringRecordError):
            m.check(obj, expected_sha=SHA)

    def test_complete_record_is_only_attestation_completeness(self):
        result = m.check(complete(), expected_sha=SHA)
        self.assertEqual(result["required_signals"], 11)
        self.assertEqual(result["verified_signal_records"], 11)
        for x in ("monitoring_runtime_confirmed", "alert_delivery_confirmed",
                  "owner_independently_confirmed", "pilot_authorized"):
            self.assertIs(result[x], False)
        self.assertNotIn("ops-primary", json.dumps(result))
        self.assertNotIn("artifact://", json.dumps(result))

    def test_missing_signal_and_invalid_release_fail_closed(self):
        obj = complete()
        obj["signals"].pop("backup_age_and_recovery_readiness")
        with self.assertRaises(m.MonitoringRecordError):
            m.check(obj, expected_sha=SHA)
        obj = complete()
        with self.assertRaises(m.MonitoringRecordError):
            m.check(obj, expected_sha="b" * 40)
        with self.assertRaises(m.MonitoringRecordError):
            m.draft("not-a-sha")

    def test_each_missing_owner_escalation_rule_or_exercise_blocks(self):
        for key, value in (
            ("status", "pending"),
            ("owner_role", ""),
            ("escalation_role", ""),
            ("owner_role", "a/b?secret=1"),
            ("severity", "unknown"),
            ("cadence_minutes", 0),
            ("response_minutes", -1),
            ("response_minutes", True),
            ("alert_rule_ref", ""),
            ("exercise_evidence_ref", "https://example.invalid/unsafe"),
            ("exercised_at_utc", "2026-10-10T17:30:00+03:30"),
            ("exercised_at_utc", "bad timestamp"),
        ):
            obj = complete()
            obj["signals"]["clamav_scanner_health"][key] = value
            with self.subTest(field=key, value=str(value)), \
                 self.assertRaises(m.MonitoringRecordError):
                m.check(obj, expected_sha=SHA)

    def test_unexpected_fields_are_rejected(self):
        obj = complete()
        obj["signals"]["api_liveness_and_readiness"]["credential"] = "danger"
        with self.assertRaises(m.MonitoringRecordError):
            m.check(obj, expected_sha=SHA)
        obj = complete()
        obj["extra"] = "something"
        with self.assertRaises(m.MonitoringRecordError):
            m.check(obj, expected_sha=SHA)
        obj = complete()
        obj["environment_ref"] = "https://example.invalid/environment"
        with self.assertRaises(m.MonitoringRecordError):
            m.check(obj, expected_sha=SHA)

    def test_init_exclusive_and_check_never_claims_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pending.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(["init", "--sha", SHA, "--output", str(path)]), 0)
            self.assertEqual(json.loads(path.read_text())["release_sha"], SHA)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(m.main(["init", "--sha", SHA, "--output", str(path)]), 2)
                self.assertEqual(m.main(["check", str(path),
                                         "--expected-sha", SHA]), 1)
            valid = Path(d) / "valid.json"
            valid.write_text(json.dumps(complete()))
            valid.chmod(0o600)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(m.main(["check", str(valid),
                                         "--expected-sha", SHA]), 0)
            self.assertIn("NOT established", output.getvalue())

    @unittest.skipUnless(os.name == "posix", "POSIX private-record permissions")
    def test_draft_is_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "draft.json"
            previous = os.umask(0)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.main(["init", "--sha", SHA, "--output", str(target)]), 0)
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_duplicate_keys_and_nonstandard_json_never_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "record.json"
            baseline = json.dumps(complete())
            mutated = [
                # A shadowed last-key override must never select a false PASS.
                baseline[:-1] + ', "release_sha": "' + SHA + '"}',
                baseline.replace('"status": "verified"', '"status": "verified", "status": "pending"', 1),
                baseline.replace('"cadence_minutes": 5', '"cadence_minutes": NaN', 1),
                baseline.replace('"response_minutes": 30', '"response_minutes": Infinity', 1),
            ]
            for payload in mutated:
                target.write_text(payload)
                target.chmod(0o600)
                with self.subTest(payload_kind=mutated.index(payload)):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        self.assertNotEqual(
                            m.main(["check", str(target), "--expected-sha", SHA]), 0,
                        )
                    self.assertNotIn("ops-primary", stderr.getvalue())

    @unittest.skipUnless(os.name == "posix", "POSIX private-record permissions")
    def test_world_or_group_readable_records_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "record.json"
            target.write_text(json.dumps(complete()))
            for mode in (0o644, 0o640, 0o604):
                target.chmod(mode)
                with self.subTest(mode=oct(mode)):
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertNotEqual(
                            m.main(["check", str(target), "--expected-sha", SHA]), 0,
                        )

    def test_symlink_nonregular_and_oversized_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "record.json"
            target.write_text(json.dumps(complete()))
            target.chmod(0o600)
            link = root / "link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                pass
            else:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(
                        m.main(["check", str(link), "--expected-sha", SHA]), 0,
                    )
                    self.assertEqual(
                        m.main(["init", "--sha", SHA, "--output", str(link)]), 2,
                    )
                self.assertEqual(json.loads(target.read_text())["release_sha"], SHA)
            huge = root / "huge.json"
            huge.write_bytes(b" " * (m.MAX_MONITORING_RECORD_BYTES + 1))
            huge.chmod(0o600)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(
                    m.main(["check", str(huge), "--expected-sha", SHA]), 0,
                )
                self.assertNotEqual(
                    m.main(["check", str(root), "--expected-sha", SHA]), 0,
                )
            if hasattr(os, "mkfifo"):
                fifo = root / "pipe"
                os.mkfifo(fifo, 0o600)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(
                        m.main(["check", str(fifo), "--expected-sha", SHA]), 0,
                    )

    def test_malformed_data_is_rejected_without_raw_echo(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text("PRIVATE-CLAIM-SECRET")
            # This test exercises malformed JSON, not public-file permissions.
            # A separate adversarial test asserts the latter fails closed.
            path.chmod(0o600)
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                self.assertEqual(m.main(["check", str(path), "--expected-sha", SHA]), 2)
            self.assertNotIn("PRIVATE-CLAIM-SECRET", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
