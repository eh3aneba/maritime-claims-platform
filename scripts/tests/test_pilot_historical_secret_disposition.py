"""Offline eight-case historic-secret evidence index regressions; synthetic refs only."""
from __future__ import annotations

from copy import deepcopy
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_historical_secret_disposition as p  # noqa: E402

SHA = "a" * 40
WHEN = "2026-11-19T07:00:00Z"
REVIEWED = "2026-11-19T08:00:00Z"
SCANNED = "2026-11-19T08:30:00Z"


def complete() -> dict:
    row = p.draft(SHA)
    row.update({
        "security_owner_role": "security-owner",
        "independent_reviewer_role": "independent-auditor",
        "review_ticket_ref": "ticket://fictional-security-review",
        "review_completed_at_utc": REVIEWED,
    })
    row["full_history_scan"].update({
        "event": "workflow_dispatch", "status": "success",
        "entire_history_confirmed": True,
        "run_ref": "artifact://synthetic-history-scan",
        "observed_at_utc": SCANNED,
    })
    for key, entry in row["findings"].items():
        entry.update({
            "classification": "confirmed_synthetic_never_issued",
            "inventory_comparison_ref": "artifact://synthetic-inventory-" + key,
            "access_review_ref": "artifact://synthetic-access-" + key,
            "disposition_ref": "artifact://synthetic-decision-" + key,
            "reviewed_at_utc": WHEN,
        })
    return row


class HistoricalSecretDispositionTests(unittest.TestCase):
    def test_no_go_draft_contains_exact_public_source_list_only(self):
        obj = p.draft(SHA)
        self.assertEqual(set(obj["findings"]), set(p.FINDINGS))
        self.assertEqual(len(obj["findings"]), 8)
        self.assertTrue(all(r["classification"] == "unresolved" for r in obj["findings"].values()))
        self.assertNotIn("password", json.dumps(obj).lower())
        with self.assertRaises(p.DispositionError):
            p.check(obj, expected_sha=SHA)

    def test_valid_synthetic_record_is_structural_only(self):
        result = p.check(complete(), expected_sha=SHA)
        self.assertEqual(result["historical_findings_structurally_disposed"], 8)
        self.assertTrue(all(v is False for k, v in result.items() if k.endswith("_verified") or k.endswith("_authorized")))
        self.assertNotIn("artifact://", json.dumps(result))

    def test_each_of_eight_requires_independent_inventory_access_disposition(self):
        for key in p.FINDINGS:
            for field in ("inventory_comparison_ref", "access_review_ref", "disposition_ref"):
                candidate = complete()
                candidate["findings"][key][field] = ""
                with self.subTest(key=key, field=field), self.assertRaises(p.DispositionError):
                    p.check(candidate, expected_sha=SHA)

    def test_duplicate_receipts_malformed_identity_and_missing_case_fail(self):
        candidate = complete()
        candidate["findings"]["F08"]["disposition_ref"] = candidate["findings"]["F07"]["disposition_ref"]
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)
        candidate = complete()
        candidate["findings"]["F03"]["inventory_comparison_ref"] = candidate["findings"]["F02"]["inventory_comparison_ref"]
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)
        candidate = complete()
        candidate["findings"]["F04"]["source_line"] = True
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)
        candidate = complete()
        candidate["findings"]["F04"]["source_commit_prefix"] = SHA
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)
        candidate = complete()
        candidate["findings"].pop("F08")
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)

    def test_real_or_reused_credential_must_document_remediation(self):
        candidate = complete()
        row = candidate["findings"]["F02"]
        row["classification"] = "actual_or_reused"
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)
        row["revocation_rotation_ref"] = "artifact://synthetic-revocation-F02"
        self.assertEqual(p.check(candidate, expected_sha=SHA)["historical_findings_structurally_disposed"], 8)
        row["classification"] = "confirmed_synthetic_never_issued"
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)
        row["classification"] = ["actual_or_reused"]
        with self.assertRaises(p.DispositionError):
            p.check(candidate, expected_sha=SHA)

    def test_full_history_must_be_post_review_scheduled_equivalent_success(self):
        for field, bad in (
            ("event", "push"), ("event", "pull_request"),
            ("status", "failure"), ("status", "pending"),
            ("entire_history_confirmed", 1),
            ("entire_history_confirmed", False),
            ("release_sha", "b" * 40),
            ("run_ref", ""),
            ("observed_at_utc", WHEN),
        ):
            obj = complete()
            obj["full_history_scan"][field] = bad
            with self.subTest(field=field, bad=str(bad)), self.assertRaises(p.DispositionError):
                p.check(obj, expected_sha=SHA)

    def test_review_roles_times_and_refs_are_fail_closed(self):
        for field, bad in (
            ("security_owner_role", "independent-auditor"),
            ("independent_reviewer_role", ""),
            ("security_owner_role", "real/user?secret"),
            ("review_ticket_ref", "https://private.example/token"),
            ("review_completed_at_utc", "2026-11-19T08:00:00+00:00"),
            ("review_completed_at_utc", "2026-11-18T08:00:00Z"),
            ("release_sha", "b" * 40),
        ):
            obj = complete()
            obj[field] = bad
            with self.subTest(field=field), self.assertRaises(p.DispositionError):
                p.check(obj, expected_sha=SHA)

    def test_exclusive_private_draft_and_no_go_check(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "draft.json"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(p.main(["init", "--release-sha", SHA, "--output", str(target)]), 0)
            self.assertIn("NO-GO", out.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(p.main(["init", "--release-sha", SHA, "--output", str(target)]), 2)
                self.assertNotEqual(p.main(["check", str(target), "--expected-sha", SHA]), 0)
            valid = Path(folder) / "complete.json"
            valid.write_text(json.dumps(complete()))
            valid.chmod(0o600)
            with contextlib.redirect_stdout(out):
                self.assertEqual(p.main(["check", str(valid), "--expected-sha", SHA]), 0)

    @unittest.skipUnless(os.name == "posix", "POSIX evidence file permissions")
    def test_private_creation_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "private.json"
            before = os.umask(0)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(p.main(["init", "--release-sha", SHA, "--output", str(target)]), 0)
            finally:
                os.umask(before)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX evidence file permissions")
    def test_public_records_never_count_as_dispositions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "record.json"
            path.write_text(json.dumps(complete()))
            for mode in (0o644, 0o640, 0o604):
                path.chmod(mode)
                with self.subTest(mode=oct(mode)), contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(path), "--expected-sha", SHA]), 0)

    def test_nonregular_symlink_oversize_duplicate_keys_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "record.json"
            baseline = json.dumps(complete())
            variants = (
                baseline[:-1] + ', "release_sha": "' + SHA + '"}',
                baseline.replace('"status": "success"', '"status": "success", "status": "success"', 1),
                baseline.replace('"source_line": 41', '"source_line": NaN', 1),
                baseline.replace('"entire_history_confirmed": true', '"entire_history_confirmed": Infinity', 1),
            )
            for index, payload in enumerate(variants):
                path.write_text(payload)
                path.chmod(0o600)
                with self.subTest(index=index), contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(path), "--expected-sha", SHA]), 0)
            path.write_text(baseline)
            path.chmod(0o600)
            link = root / "linked.json"
            try:
                link.symlink_to(path)
            except (NotImplementedError, OSError):
                pass
            else:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(link), "--expected-sha", SHA]), 0)
            oversized = root / "large.json"
            oversized.write_bytes(b" " * (p.MAX_RECORD_BYTES + 1))
            oversized.chmod(0o600)
            with contextlib.redirect_stderr(io.StringIO()):
                for bad_path in (root, oversized):
                    self.assertNotEqual(p.main(["check", str(bad_path), "--expected-sha", SHA]), 0)
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo"
                os.mkfifo(fifo, 0o600)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(fifo), "--expected-sha", SHA]), 0)

    def test_bad_record_does_not_echo_operator_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text("PRIVATE-SECRET-VALUE")
            path.chmod(0o600)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertNotEqual(p.main(["check", str(path), "--expected-sha", SHA]), 0)
            self.assertNotIn("PRIVATE-SECRET-VALUE", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
