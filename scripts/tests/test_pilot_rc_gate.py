"""Regression tests for the fail-closed Pilot v1 release-candidate record gate."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_rc_gate import IMAGES, PROOFS, draft, main, validate  # noqa: E402

SHA = "a" * 40
STAMP = "2026-10-09T09:30:00Z"


def complete_record():
    record = draft(SHA)
    record["alembic_head"] = "0224_obs_refresh_recovery_anchor"
    record["features"]["sftp_ingestion"] = "enabled"
    record["environment_id"] = "synthetic-private-pilot"
    record["configuration_contract_ref"] = "secure-change-record-rc-001"
    record["known_limitations_ref"] = "reviewed-limitations-record-rc-001"
    for key in IMAGES:
        record["images"][key] = "registry.example/mcri-" + key + "@sha256:" + "b" * 64
    for key in PROOFS:
        record["proofs"][key] = {
            "result": "pass", "evidence_ref": "reviewed-artifact-" + key,
            "owner": "pilot-operator", "observed_at_utc": STAMP,
        }
    return record


class PilotRCGateTests(unittest.TestCase):
    def test_draft_is_no_go(self):
        issues = validate(draft(SHA), SHA)
        self.assertTrue(issues)
        self.assertTrue(any("branch_protection_fail_closed" in issue for issue in issues))

    def test_complete_record_is_structurally_valid_only(self):
        self.assertEqual([], validate(complete_record(), SHA))

    def test_sftp_disabled_requires_explicit_checked_disablement_record(self):
        record = complete_record()
        record["features"]["sftp_ingestion"] = "disabled"
        self.assertTrue(any("real_sftp_governed_lifecycle" in error
                            for error in validate(record, SHA)))
        proof = record["proofs"]["real_sftp_governed_lifecycle"]
        proof["result"] = "not_applicable"
        # This is only a reviewable operator reference, not host proof.
        proof["evidence_ref"] = "reviewed-disabled-sftp-config-and-ingestion-controls"
        self.assertEqual(validate(record, SHA), [])
        proof["evidence_ref"] = ""
        self.assertTrue(any("real_sftp_governed_lifecycle.evidence_ref" in error
                            for error in validate(record, SHA)))
        proof["evidence_ref"] = "reviewed-disabled-sftp-config-and-ingestion-controls"
        proof["owner"] = ""
        self.assertTrue(any("real_sftp_governed_lifecycle.owner" in error
                            for error in validate(record, SHA)))

    def test_sftp_enabled_never_accepts_not_applicable(self):
        record = complete_record()
        record["proofs"]["real_sftp_governed_lifecycle"]["result"] = "not_applicable"
        self.assertTrue(any("real_sftp_governed_lifecycle" in error
                            for error in validate(record, SHA)))

    def test_missing_unselected_or_malformed_feature_mode_fails_closed(self):
        for bad in (
            "pending", "unknown", "", None, True,
            "disabled;enabled",
        ):
            with self.subTest(bad=bad):
                record = complete_record()
                record["features"]["sftp_ingestion"] = bad
                self.assertTrue(any("features.sftp_ingestion" in error
                                    for error in validate(record, SHA)))
        for bad in (None, {}, {"sftp_ingestion": "disabled", "future": "x"}, "disabled"):
            with self.subTest(malformed=bad):
                record = complete_record()
                record["features"] = bad
                self.assertTrue(any("features.sftp_ingestion" in error
                                    for error in validate(record, SHA)))

    def test_old_schema_is_rejected_without_migration(self):
        record = complete_record()
        record["schema"] = "mcri-pilot-rc-v1"
        self.assertTrue(any("schema:" in error for error in validate(record, SHA)))

    def test_wrong_or_short_commit_fails(self):
        self.assertTrue(validate(complete_record(), "c" * 40))
        self.assertTrue(validate(complete_record(), "deadbeef"))

    def test_missing_image_digest_fails(self):
        data = complete_record()
        data["images"]["postgres"] = "postgres:18.4"
        self.assertTrue(any("images.postgres" in e for e in validate(data, SHA)))

    def test_malformed_or_extra_proofs_fail(self):
        data = complete_record()
        del data["proofs"]["restore_drill"]
        self.assertTrue(validate(data, SHA))
        data = complete_record()
        data["proofs"]["imaginary_gate"] = {"result": "pass"}
        self.assertTrue(validate(data, SHA))

    def test_one_pending_and_one_missing_owner_fail(self):
        data = complete_record()
        data["proofs"]["real_sftp_governed_lifecycle"]["result"] = "pending"
        data["proofs"]["restore_drill"]["owner"] = ""
        failures = validate(data, SHA)
        self.assertTrue(any("real_sftp_governed_lifecycle" in e for e in failures))
        self.assertTrue(any("restore_drill.owner" in e for e in failures))

    def test_utc_required(self):
        data = complete_record()
        data["proofs"]["rollback_drill"]["observed_at_utc"] = "2026-10-09T12:30:00+03:00"
        self.assertTrue(validate(data, SHA))

    def test_proof_timestamp_requires_canonical_utc_seconds(self):
        invalid_timestamps = (
            "2026-10-09T09:30:00.123Z",  # fractional seconds
            "2026-10-09T09:30Z",  # no seconds
            "2026-10-09 09:30:00Z",  # noncanonical separator
            "2026-10-09T09:30:00+00:00",  # UTC but not the required Z suffix
            "2026-1-9T9:30:00Z",  # noncanonical zero padding
            "2026-02-30T09:30:00Z",  # impossible calendar date
        )
        for stamp in invalid_timestamps:
            with self.subTest(stamp=stamp):
                data = complete_record()
                data["proofs"]["rollback_drill"]["observed_at_utc"] = stamp
                self.assertTrue(
                    any("rollback_drill.observed_at_utc" in problem
                        for problem in validate(data, SHA))
                )

    def test_missing_and_extra_top_level_keys_fail(self):
        data = complete_record()
        data["unexpected"] = "pretend success"
        self.assertTrue(validate(data, SHA))

    def test_non_object_fails(self):
        self.assertTrue(validate([], SHA))

    def test_init_never_overwrites_and_check_draft_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release.json"
            self.assertEqual(0, main(["init", "--output", str(output), "--release-sha", SHA]))
            self.assertEqual(2, main(["init", "--output", str(output), "--release-sha", SHA]))
            self.assertEqual(1, main(["check", str(output), "--expected-sha", SHA]))

    def test_missing_file_fails(self):
        self.assertEqual(1, main(["check", "/no/such/release.json", "--expected-sha", SHA]))


if __name__ == "__main__":
    unittest.main()
