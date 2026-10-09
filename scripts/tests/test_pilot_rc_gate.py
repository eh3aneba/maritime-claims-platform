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
