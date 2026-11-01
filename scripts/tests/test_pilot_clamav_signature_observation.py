"""Fixed-clock, network-free tests for read-only scanner metadata observation."""
from datetime import datetime, timezone, timedelta
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from scripts import pilot_clamav_signature_observation as probe

SHA = "a" * 40
RAW = "ClamAV 1.5.4/28164/Sun Oct 25 06:24:12 2026"
NOW = datetime(2026, 11, 1, 6, 24, 12, tzinfo=timezone.utc)


class SignatureObservationTests(unittest.TestCase):
    def evaluate(self, raw=RAW, now=NOW, zone="UTC"):
        return probe.evaluate(raw, observed_at=now, release_sha=SHA, signature_timezone=zone)

    def test_fixed_clock_exact_age_is_not_a_freshness_verdict(self):
        report = self.evaluate()
        self.assertEqual(report["signature_age_seconds_signed"], 7 * 86400)
        self.assertEqual(report["engine_version"], "1.5.4")
        self.assertEqual(report["signature_database_serial"], 28164)
        self.assertEqual(report["observation_state"], "metadata_observed")
        self.assertFalse(report["freshness_policy_evaluated"])
        self.assertFalse(report["acceptable_freshness_threshold_defined"])
        self.assertFalse(report["customer_admission_policy_changed"])
        self.assertFalse(report["pilot_authorized"])
        self.assertNotIn(RAW, json.dumps(report))

    def test_zero_age_and_arbitrarily_old_definitions_do_not_define_thresholds(self):
        for age in (0, 1, 86400, 3650 * 86400):
            report = self.evaluate(now=NOW - timedelta(days=7) + timedelta(seconds=age))
            self.assertEqual(report["signature_age_seconds_signed"], age)
            self.assertEqual(report["observation_state"], "metadata_observed")
            self.assertFalse(report["freshness_policy_evaluated"])

    def test_future_clock_is_explicit_and_not_clamped_to_zero(self):
        report = self.evaluate(now=NOW - timedelta(days=8))
        self.assertEqual(report["observation_state"], "future_dated")
        self.assertEqual(report["signature_age_seconds_signed"], -86400)

    def test_timezone_is_required_and_aware_clock_is_normalized(self):
        report = self.evaluate(zone=None)
        self.assertEqual(report["observation_state"], "signature_timezone_unresolved")
        self.assertIsNone(report["signature_age_seconds_signed"])
        offset = NOW.astimezone(timezone(timedelta(hours=3, minutes=30)))
        self.assertEqual(self.evaluate(now=offset), self.evaluate())
        with self.assertRaises(ValueError):
            self.evaluate(now=NOW.replace(tzinfo=None))

    def test_malformed_missing_and_untrusted_strings_never_leak(self):
        for raw in ("", "ClamAV 1.5.4", RAW + "\nPRIVATE", RAW + "\0", "PRIVATE",
                    RAW.replace("Sun", "Mon"), RAW.replace("28164", "0"),
                    RAW.replace("Oct 25", "Feb 31"), "X" * 257, None):
            with self.subTest(raw=raw):
                report = self.evaluate(raw=raw)
                self.assertEqual(report["observation_state"], "unavailable_or_malformed")
                self.assertIsNone(report["signature_age_seconds_signed"])
                self.assertNotIn("PRIVATE", json.dumps(report))

    def test_invalid_release_sha_and_undeclared_zone_are_rejected(self):
        for sha, zone in (("main", "UTC"), (SHA, "Asia/Tehran")):
            with self.assertRaises(ValueError):
                probe.evaluate(RAW, observed_at=NOW, release_sha=sha, signature_timezone=zone)

    def test_transport_sends_only_version_and_handles_fragmented_response(self):
        connection = MagicMock()
        connection.recv.side_effect = [RAW[:8].encode(), RAW[8:].encode() + b"\0"]
        manager = MagicMock()
        manager.__enter__.return_value = connection
        with patch.object(probe.socket, "create_connection", return_value=manager) as connect:
            self.assertEqual(probe.observe_version(port=13310), RAW)
        connect.assert_called_once_with(("127.0.0.1", 13310), timeout=5)
        connection.sendall.assert_called_once_with(b"zVERSION\0")

    def test_transport_rejects_incomplete_or_overlong_frames(self):
        for chunks in ([b"ClamAV", b""], [b"X" * 257], [RAW.encode() + b"\0PRIVATE"]):
            connection = MagicMock()
            connection.recv.side_effect = chunks
            manager = MagicMock()
            manager.__enter__.return_value = connection
            with patch.object(probe.socket, "create_connection", return_value=manager):
                with self.assertRaises(ValueError):
                    probe.observe_version(port=13310)

    def test_cli_guard_refuses_before_connecting(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            with patch.object(probe, "observe_version") as observe:
                with redirect_stderr(StringIO()):
                    self.assertEqual(probe.main(["--release-sha", SHA, "--output", "/unused"]), 2)
                observe.assert_not_called()

    def test_slow_fragment_stream_cannot_extend_the_total_read_deadline(self):
        connection = MagicMock()
        connection.recv.return_value = b"ClamAV"
        manager = MagicMock()
        manager.__enter__.return_value = connection
        with patch.object(probe.socket, "create_connection", return_value=manager):
            with patch.object(probe.time, "monotonic", side_effect=[0, 0, 0, 6]):
                with self.assertRaises(TimeoutError):
                    probe.observe_version(port=13310, timeout=5)
        connection.recv.assert_called_once()

    def test_cli_records_failure_without_error_contents_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            args = ["--release-sha", SHA, "--signature-timezone", "UTC", "--output", str(path)]
            with patch.dict(os.environ, {"APP_ENV": "test", "MCRI_SYNTHETIC_ONLY_CONFIRM": "YES"}):
                with patch.object(probe, "observe_version", side_effect=OSError("PRIVATE")):
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        self.assertEqual(probe.main(args), 2)
                        original = path.read_bytes()
                        self.assertEqual(probe.main(args), 2)
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn(b"PRIVATE", original)
            self.assertEqual(json.loads(original)["observation_state"], "unavailable_or_malformed")


if __name__ == "__main__":
    unittest.main()
