"""Offline regression checks for rollback rehearsal record gate."""
from copy import deepcopy
from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_rollback_rehearsal as p  # noqa: E402

FROM_SHA = "a" * 40
TO_SHA = "b" * 40
REVISION = "0224_obs_refresh_recovery_anchor"
WHEN = "2026-10-10T19:00:00Z"
AFTER = "2026-10-10T19:15:00Z"


def ready(mode="application_only"):
    obj = p.draft(FROM_SHA, TO_SHA)
    obj.update({
        "environment_ref": "runbook://pilot-safe-rehearsal",
        "mode": mode,
        "from_alembic_revision": REVISION,
        "to_alembic_revision": REVISION if mode == "application_only" else "0223_pre_recovery_anchor",
        "primary_operator_role": "primary-operator",
        "independent_approver_role": "separate-approver",
        "exercise_started_at_utc": WHEN,
        "exercise_completed_at_utc": AFTER,
        "rollback_result": "pass",
        "explicit_human_authorized": True,
        "unsafe_database_downgrade_performed": False,
        "live_database_restored": mode == "recover_paired_backup",
    })
    for service in p.SERVICES:
        obj["from_images"][service] = "example.test/" + service + "@sha256:" + "c" * 64
        obj["to_images"][service] = "example.test/" + service + "@sha256:" + "d" * 64
    for name in p.BASE_EVIDENCE:
        obj["evidence"][name] = "artifact://synthetic-" + name
    if mode == "recover_paired_backup":
        for name in p.DB_RESTORE_EVIDENCE:
            obj["evidence"][name] = "artifact://synthetic-" + name
    return obj


class RollbackRehearsalTests(unittest.TestCase):
    def valid(self, obj):
        return p.check(obj, from_sha=FROM_SHA, to_sha=TO_SHA)

    def test_draft_never_passes_and_two_distinct_sha_required(self):
        draft = p.draft(FROM_SHA, TO_SHA)
        self.assertEqual(draft["mode"], "pending")
        self.assertFalse(draft["explicit_human_authorized"])
        with self.assertRaises(p.RollbackEvidenceError):
            self.valid(draft)
        for bad in ((FROM_SHA, FROM_SHA), ("bad", TO_SHA)):
            with self.assertRaises(p.RollbackEvidenceError):
                p.draft(*bad)

    def test_application_only_requires_identical_schema_and_no_restore(self):
        result = self.valid(ready())
        self.assertTrue(result["rollback_record_complete"])
        self.assertTrue(all(v is False for k,v in result.items() if k.endswith("_verified") or k.endswith("_authorized")))
        for field, value in (
            ("to_alembic_revision", "0223_pre_recovery_anchor"),
            ("live_database_restored", True),
            ("unsafe_database_downgrade_performed", True),
        ):
            obj = ready()
            obj[field] = value
            with self.subTest(field=field), self.assertRaises(p.RollbackEvidenceError):
                self.valid(obj)

    def test_database_recovery_requires_paired_evidence(self):
        obj = ready("recover_paired_backup")
        self.assertTrue(self.valid(obj)["rollback_record_complete"])
        for key in p.DB_RESTORE_EVIDENCE:
            bad = deepcopy(obj)
            bad["evidence"][key] = ""
            with self.subTest(key=key), self.assertRaises(p.RollbackEvidenceError):
                self.valid(bad)
        extra = ready()
        extra["evidence"]["restore_operation_ref"] = "artifact://should-not-claim-restore"
        with self.assertRaises(p.RollbackEvidenceError):
            self.valid(extra)

    def test_requires_real_image_digest_pairs_and_changed_release(self):
        for mutate in (
            lambda o: o["to_images"].__setitem__("api", "registry/image:mutable"),
            lambda o: o["to_images"].update(o["from_images"]),
            lambda o: o["to_images"].pop("worker"),
            lambda o: o.update(to_release_sha=FROM_SHA),
        ):
            item = ready()
            mutate(item)
            with self.assertRaises(p.RollbackEvidenceError):
                self.valid(item)

    def test_independent_roles_approval_and_time_order(self):
        for field, value in (
            ("independent_approver_role", "primary-operator"),
            ("primary_operator_role", ""),
            ("explicit_human_authorized", False),
            ("rollback_result", "pending"),
            ("exercise_completed_at_utc", "2026-10-10T18:00:00Z"),
            ("exercise_completed_at_utc", "2026-10-10T19:15:00+00:00"),
        ):
            item = ready()
            item[field] = value
            with self.subTest(field=field), self.assertRaises(p.RollbackEvidenceError):
                self.valid(item)

    def test_missing_key_or_malformed_reference_rejected_without_leakage(self):
        item = ready()
        item["evidence"]["operator_review_ref"] = "https://example.com/secret"
        with self.assertRaises(p.RollbackEvidenceError) as exc:
            self.valid(item)
        self.assertNotIn("secret", str(exc.exception))
        item = ready()
        item.pop("from_images")
        with self.assertRaises(p.RollbackEvidenceError):
            self.valid(item)
        item = ready()
        item["environment_ref"] = "../secret"
        with self.assertRaises(p.RollbackEvidenceError):
            self.valid(item)

    def test_exclusive_init_and_unverified_record_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "draft.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(p.main(["init", "--from-sha", FROM_SHA,
                    "--to-sha", TO_SHA, "--output", str(path)]), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(p.main(["init", "--from-sha", FROM_SHA,
                    "--to-sha", TO_SHA, "--output", str(path)]), 2)
                self.assertEqual(p.main(["check", str(path), "--from-sha",
                    FROM_SHA, "--to-sha", TO_SHA]), 1)
            valid = Path(d) / "valid.json"
            valid.write_text(json.dumps(ready()))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(p.main(["check", str(valid), "--from-sha",
                    FROM_SHA, "--to-sha", TO_SHA]), 0)
            self.assertIn("NOT proof", out.getvalue())

    def test_invalid_json_never_echoes_private_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "invalid.json"
            path.write_text("synthetic-private-text")
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(p.main(["check", str(path), "--from-sha",
                    FROM_SHA, "--to-sha", TO_SHA]), 2)
            self.assertNotIn("synthetic-private-text", output.getvalue())


if __name__ == "__main__":
    unittest.main()
