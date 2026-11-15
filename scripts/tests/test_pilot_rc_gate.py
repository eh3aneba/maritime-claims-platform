"""Regression tests for the fail-closed Pilot v1 release-candidate record gate."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_rc_gate import FEATURE_MODES, IMAGES, PROOFS, SCHEMA, draft, main, validate  # noqa: E402

SHA = "a" * 40
STAMP = "2026-10-09T09:30:00Z"


def complete_record():
    record = draft(SHA)
    record["alembic_head"] = "0224_obs_refresh_recovery_anchor"
    for feature in FEATURE_MODES:
        record["features"][feature] = "enabled"
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
    def test_active_release_operator_docs_use_v5_and_historical_docs_do_not_misstate_current_schema(self):
        """Prevent a stale v4 operator command from bypassing the new PDF admission proof."""
        repo_root = Path(__file__).resolve().parents[2]
        active = (
            repo_root / "docs/operations/PILOT_RELEASE_CANDIDATE.md"
        ).read_text(encoding="utf-8")
        v5 = (
            repo_root / "docs/pilot/PILOT_RC_V5_SIGNED_PDF_ADMISSION.md"
        ).read_text(encoding="utf-8")
        rehearsal = (
            repo_root / "docs/operations/PILOT_FRESH_HOST_REHEARSAL.md"
        ).read_text(encoding="utf-8")
        old_v4 = (
            repo_root / "docs/pilot/PILOT_RC_V4_SECURITY_ADMISSION.md"
        ).read_text(encoding="utf-8")
        old_v3 = (
            repo_root / "docs/pilot/PILOT_RC_V3_FEATURE_ADMISSION.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(SCHEMA, "mcri-pilot-rc-v5")
        self.assertIn(SCHEMA, active)
        self.assertIn(SCHEMA, v5)
        self.assertIn("signed_pdf_inbound_scope_security_disposition", active)
        self.assertIn("signed_pdf_inbound_scope_security_disposition", v5)
        self.assertIn("signed_pdf_inbound_scope_security_disposition", rehearsal)
        self.assertIn("PILOT_RC_V5_SIGNED_PDF_ADMISSION.md", rehearsal)
        self.assertIn("HISTORICAL v4 DOCUMENT", old_v4)
        self.assertIn(SCHEMA, old_v4)
        self.assertIn(SCHEMA, old_v3)
        self.assertNotIn("--output /secure/pilot-releases/rc-v4.json", old_v4)

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
                self.assertTrue(any("features:" in error for error in validate(record, SHA)))

    def test_draft_requires_explicit_ai_and_persian_source_mode(self):
        draft_record = draft(SHA)
        self.assertEqual(
            draft_record["features"],
            {key: "pending" for key in FEATURE_MODES},
        )
        errors = validate(draft_record, SHA)
        self.assertTrue(any("features.ai_inference" in error for error in errors))
        self.assertTrue(any("features.persian_critical_extraction" in error
                            for error in errors))
        self.assertTrue(any("actual_feature_flag_enforcement" in error
                            for error in errors))

    def test_disabled_ai_and_persian_critical_extraction_require_attested_off_mode(self):
        record = complete_record()
        disabled = {
            "ai_inference": "local_ai_independent_acceptance",
            "persian_critical_extraction": "persian_critical_ocr_acceptance",
        }
        for feature, proof_key in disabled.items():
            record["features"][feature] = "disabled"
            self.assertTrue(any(proof_key in error for error in validate(record, SHA)))
            proof = record["proofs"][proof_key]
            proof["result"] = "not_applicable"
            proof["evidence_ref"] = "observed-deployed-disabled-flag-" + feature
        self.assertEqual([], validate(record, SHA))
        for proof_key in disabled.values():
            record["proofs"][proof_key]["evidence_ref"] = ""
            self.assertTrue(any(proof_key + ".evidence_ref" in error
                                for error in validate(record, SHA)))
            record["proofs"][proof_key]["evidence_ref"] = "observed-disabled-feature"
            record["proofs"][proof_key]["owner"] = ""
            self.assertTrue(any(proof_key + ".owner" in error
                                for error in validate(record, SHA)))
            record["proofs"][proof_key]["owner"] = "pilot-operator"

    def test_enabled_ai_or_persian_extraction_cannot_bypass_acceptance(self):
        for feature, proof_key in (
            ("ai_inference", "local_ai_independent_acceptance"),
            ("persian_critical_extraction", "persian_critical_ocr_acceptance"),
        ):
            with self.subTest(feature=feature):
                record = complete_record()
                record["proofs"][proof_key]["result"] = "not_applicable"
                self.assertTrue(any(proof_key in error for error in validate(record, SHA)))
                record["features"][feature] = "disabled"
                record["proofs"][proof_key]["result"] = "pass"
                self.assertTrue(any(proof_key in error for error in validate(record, SHA)))

    def test_feature_selection_is_strict_and_no_dispute_gate_is_exempt(self):
        for feature in FEATURE_MODES:
            for bad in ("pending", "unknown", "", None, True, "enabled;disabled"):
                with self.subTest(feature=feature, bad=bad):
                    record = complete_record()
                    record["features"][feature] = bad
                    self.assertTrue(any("features." + feature in e for e in validate(record, SHA)))
        record = complete_record()
        for feature, proof_key in (
            ("sftp_ingestion", "real_sftp_governed_lifecycle"),
            ("ai_inference", "local_ai_independent_acceptance"),
            ("persian_critical_extraction", "persian_critical_ocr_acceptance"),
        ):
            record["features"][feature] = "disabled"
            record["proofs"][proof_key]["result"] = "not_applicable"
        self.assertEqual([], validate(record, SHA))
        for required in (
            "actual_feature_flag_enforcement",
            "source_discrepancy_review_and_resolution_policy",
        ):
            record["proofs"][required]["result"] = "not_applicable"
            self.assertTrue(any(required in e for e in validate(record, SHA)))
            record["proofs"][required]["result"] = "pass"

    def test_signed_pdf_inbound_policy_requires_owner_approval_even_with_optional_features_off(self):
        key = "signed_pdf_inbound_scope_security_disposition"
        # The PDF signature status is always not_checked in production today.
        # The release record cannot infer an authenticity decision from CI,
        # a source SHA, uploaded MIME, or an operator-disabled OCR feature.
        self.assertEqual(draft(SHA)["proofs"][key]["result"], "pending")
        self.assertTrue(any(key in issue for issue in validate(draft(SHA), SHA)))

        record = complete_record()
        for feature, conditional in (
            ("sftp_ingestion", "real_sftp_governed_lifecycle"),
            ("ai_inference", "local_ai_independent_acceptance"),
            ("persian_critical_extraction", "persian_critical_ocr_acceptance"),
        ):
            record["features"][feature] = "disabled"
            record["proofs"][conditional]["result"] = "not_applicable"
        self.assertEqual([], validate(record, SHA))
        for result in ("pending", "not_applicable", "failed", "unknown", None, True):
            with self.subTest(result=result):
                record["proofs"][key]["result"] = result
                self.assertTrue(any(key in e for e in validate(record, SHA)))
        record["proofs"][key]["result"] = "pass"
        for field, invalid in (
            ("evidence_ref", ""),
            ("owner", ""),
            ("observed_at_utc", "2026-11-15T10:00:00+03:30"),
        ):
            with self.subTest(field=field):
                original = record["proofs"][key][field]
                record["proofs"][key][field] = invalid
                self.assertTrue(any(key + "." + field in e for e in validate(record, SHA)))
                record["proofs"][key][field] = original
        del record["proofs"][key]
        self.assertTrue(any("proofs:" in e for e in validate(record, SHA)))

    def test_historical_secret_finding_triage_is_mandatory_not_conditional(self):
        key = "historical_secret_findings_disposition"
        # A green PR scan never implicitly clears the older Gitleaks findings.
        self.assertEqual(draft(SHA)["proofs"][key]["result"], "pending")
        self.assertTrue(any(key in issue for issue in validate(draft(SHA), SHA)))

        record = complete_record()
        self.assertEqual([], validate(record, SHA))
        for result in ("pending", "not_applicable", "failed", "unknown", None, True):
            with self.subTest(result=result):
                record["proofs"][key]["result"] = result
                self.assertTrue(any(key in issue for issue in validate(record, SHA)))
        record["proofs"][key]["result"] = "pass"

        for field, bad in (
            ("evidence_ref", ""), ("owner", ""),
            ("observed_at_utc", "2026-11-15T00:00:00+03:30"),
        ):
            with self.subTest(field=field):
                original = record["proofs"][key][field]
                record["proofs"][key][field] = bad
                self.assertTrue(any(key + "." + field in issue
                                    for issue in validate(record, SHA)))
                record["proofs"][key][field] = original

        del record["proofs"][key]
        self.assertTrue(validate(record, SHA))

    def test_old_schema_is_rejected_without_migration(self):
        record = complete_record()
        for old_schema in ("mcri-pilot-rc-v1", "mcri-pilot-rc-v2", "mcri-pilot-rc-v3", "mcri-pilot-rc-v4"):
            record["schema"] = old_schema
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

    def test_malformed_proof_entries_fail_closed_without_crashing(self):
        for malformed in (None, [], "pass", True, 123):
            with self.subTest(entry=malformed):
                record = complete_record()
                record["proofs"]["local_ai_independent_acceptance"] = malformed
                issues = validate(record, SHA)
                self.assertTrue(any("local_ai_independent_acceptance" in problem
                                    for problem in issues))

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

    def test_check_rejects_duplicate_keys_at_root_and_in_security_proof(self):
        valid = json.dumps(complete_record(), sort_keys=True)
        key = '"historical_secret_findings_disposition": {'
        start = valid.index(key)
        result_index = valid.index('"result": "pass"', start)
        # Last-value-wins parsing would mask an earlier pending proof.
        conflicting_proof = (
            valid[:result_index] + '"result": "pending", ' + valid[result_index:]
        )
        conflicting_sha = valid.replace(
            '"release_sha":', '"release_sha": "' + "c" * 40 + '", "release_sha":',
            1,
        )
        repeated_object = valid.replace(
            key, key + '"result": "pending"}, ' + key, 1,
        )
        for index, malformed in enumerate(
            (conflicting_sha, conflicting_proof, repeated_object)
        ):
            with self.subTest(case=index):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "candidate.json"
                    path.write_text(malformed, encoding="utf-8")
                    path.chmod(0o600)
                    stderr = StringIO()
                    with redirect_stderr(stderr):
                        self.assertEqual(
                            1, main(["check", str(path), "--expected-sha", SHA])
                        )
                    self.assertIn(
                        "NO-GO: cannot read JSON record (ValueError)",
                        stderr.getvalue(),
                    )
                    self.assertNotIn("pending", stderr.getvalue())

    def test_check_rejects_nonstandard_numbers_and_large_input(self):
        valid = json.dumps(complete_record(), sort_keys=True)
        invalid = valid.replace(
            '"release_sha": "' + SHA + '"', '"release_sha": NaN', 1
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            for payload in (invalid, " " * 1_048_577):
                path.write_text(payload, encoding="utf-8")
                path.chmod(0o600)
                stderr = StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(
                        1, main(["check", str(path), "--expected-sha", SHA])
                    )
                self.assertIn(
                    "NO-GO: cannot read JSON record (ValueError)",
                    stderr.getvalue(),
                )

    def test_check_accepts_unambiguous_valid_synthetic_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps(complete_record()), encoding="utf-8")
            path.chmod(0o600)
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(0, main(["check", str(path), "--expected-sha", SHA]))
            self.assertIn("RECORD COMPLETE", stdout.getvalue())
            self.assertIn("NOT pilot authorization", stdout.getvalue())

    def test_init_never_overwrites_and_check_draft_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release.json"
            self.assertEqual(0, main(["init", "--output", str(output), "--release-sha", SHA]))
            self.assertEqual(2, main(["init", "--output", str(output), "--release-sha", SHA]))
            self.assertEqual(1, main(["check", str(output), "--expected-sha", SHA]))

    @unittest.skipUnless(os.name == "posix", "POSIX owner-only file mode assertion")
    def test_init_creates_owner_only_private_record_even_if_umask_permits_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensitive-rc-draft.json"
            previous_umask = os.umask(0o000)
            try:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    code = main(["init", "--output", str(path), "--release-sha", SHA])
            finally:
                os.umask(previous_umask)
            self.assertEqual(code, 0)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(draft(SHA), json.loads(path.read_text(encoding="utf-8")))

    def test_init_rejects_existing_symlink_without_modifying_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing-rc.json"
            target.write_text("synthetic-owner-record-unchanged", encoding="utf-8")
            link = Path(directory) / "symlink-rc.json"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError):
                self.skipTest("symlink creation not supported on this platform")
            err = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(err):
                code = main(["init", "--output", str(link), "--release-sha", SHA])
            self.assertEqual(code, 2)
            self.assertIn("ERROR: cannot create record:", err.getvalue())
            self.assertNotIn(str(target), err.getvalue())
            self.assertEqual(target.read_text(encoding="utf-8"), "synthetic-owner-record-unchanged")

    @unittest.skipUnless(os.name == "posix", "POSIX private-file mode enforcement")
    def test_check_rejects_world_or_group_readable_rc_even_when_evidence_is_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "looks-approved.json"
            path.write_text(json.dumps(complete_record()), encoding="utf-8")
            for mode in (0o644, 0o640, 0o604):
                with self.subTest(mode=oct(mode)):
                    path.chmod(mode)
                    stderr = StringIO()
                    with redirect_stderr(stderr), redirect_stdout(StringIO()):
                        self.assertEqual(1, main(["check", str(path), "--expected-sha", SHA]))
                    self.assertEqual(
                        stderr.getvalue().strip(),
                        "NO-GO: cannot read JSON record (ValueError)",
                    )
            path.chmod(0o600)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(0, main(["check", str(path), "--expected-sha", SHA]))

    def test_check_rejects_symlinked_release_record_without_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "protected-evidence.json"
            target.write_text(json.dumps(complete_record()), encoding="utf-8")
            target.chmod(0o600)
            link = Path(directory) / "redirected.json"
            try:
                link.symlink_to(target)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks unavailable on this platform")
            stderr, stdout = StringIO(), StringIO()
            with redirect_stderr(stderr), redirect_stdout(stdout):
                self.assertEqual(1, main(["check", str(link), "--expected-sha", SHA]))
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(
                stderr.getvalue().strip(), "NO-GO: cannot read JSON record (ValueError)"
            )
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), complete_record())

    @unittest.skipUnless(os.name == "posix", "FIFO descriptor check on POSIX")
    def test_check_rejects_fifo_without_waiting_or_leaking_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "not-a-json-file"
            os.mkfifo(fifo, 0o600)
            stderr = StringIO()
            with redirect_stderr(stderr), redirect_stdout(StringIO()):
                self.assertEqual(1, main(["check", str(fifo), "--expected-sha", SHA]))
            self.assertEqual(
                stderr.getvalue().strip(), "NO-GO: cannot read JSON record (ValueError)"
            )

    def test_missing_file_fails(self):
        self.assertEqual(1, main(["check", "/no/such/release.json", "--expected-sha", SHA]))


if __name__ == "__main__":
    unittest.main()
