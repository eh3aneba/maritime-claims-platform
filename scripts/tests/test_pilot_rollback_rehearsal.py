"""Offline regression checks for rollback rehearsal record gate."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

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
            valid.chmod(0o600)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(p.main(["check", str(valid), "--from-sha",
                    FROM_SHA, "--to-sha", TO_SHA]), 0)
            self.assertIn("NOT proof", out.getvalue())

    def test_invalid_release_pair_does_not_create_empty_draft_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "should-not-exist.json"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(p.main(["init", "--from-sha", "invalid",
                    "--to-sha", TO_SHA, "--output", str(path)]), 2)
            self.assertFalse(path.exists())

    def test_invalid_json_never_echoes_private_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "invalid.json"
            path.write_text("synthetic-private-text")
            path.chmod(0o600)
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(p.main(["check", str(path), "--from-sha",
                    FROM_SHA, "--to-sha", TO_SHA]), 2)
            self.assertNotIn("synthetic-private-text", output.getvalue())

    @unittest.skipUnless(os.name == "posix", "POSIX private rollback evidence modes")
    def test_init_creates_private_draft_even_under_permissive_umask(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "draft.json"
            old_umask = os.umask(0)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(p.main(["init", "--from-sha", FROM_SHA,
                        "--to-sha", TO_SHA, "--output", str(path)]), 0)
            finally:
                os.umask(old_umask)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX private rollback evidence modes")
    def test_public_or_group_access_blocks_record(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rollback.json"
            path.write_text(json.dumps(ready()))
            for mode in (0o644, 0o640, 0o604, 0o660):
                path.chmod(mode)
                with self.subTest(mode=oct(mode)), contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(path), "--from-sha",
                        FROM_SHA, "--to-sha", TO_SHA]), 0)

    def test_nested_and_top_level_duplicate_keys_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rollback.json"
            valid = json.dumps(ready())
            mutations = (
                valid[:-1] + ', "explicit_human_authorized": true}',
                valid.replace('"operator_review_ref": "artifact://synthetic-operator_review_ref"',
                              '"operator_review_ref": "artifact://synthetic-operator_review_ref", '
                              '"operator_review_ref": "artifact://synthetic-operator_review_ref"', 1),
                valid.replace('"live_database_restored": false',
                              '"live_database_restored": NaN', 1),
                valid.replace('"unsafe_database_downgrade_performed": false',
                              '"unsafe_database_downgrade_performed": Infinity', 1),
            )
            for index, payload in enumerate(mutations):
                path.write_text(payload)
                path.chmod(0o600)
                with self.subTest(case=index), contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(path), "--from-sha",
                        FROM_SHA, "--to-sha", TO_SHA]), 0)

    def test_private_rollback_record_rejects_changed_file_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollback.json"
            path.write_text(json.dumps(ready()), encoding="utf-8")
            path.chmod(0o600)
            original = os.fstat
            for field in ("st_dev", "st_ino", "st_mode", "st_mtime_ns", "st_ctime_ns"):
                with self.subTest(field=field):
                    count = [0]

                    def mutate_after_read(fd):
                        info = original(fd)
                        count[0] += 1
                        if count[0] != 2:
                            return info
                        fields = {
                            key: getattr(info, key)
                            for key in ("st_dev", "st_ino", "st_mode", "st_size",
                                        "st_mtime_ns", "st_ctime_ns")
                        }
                        fields[field] += 1
                        return SimpleNamespace(**fields)

                    with patch.object(p.os, "fstat", side_effect=mutate_after_read):
                        with self.assertRaises(p.RollbackEvidenceError) as caught:
                            p._read_private_record(path)
                    self.assertEqual(count[0], 2)
                    self.assertEqual(str(caught.exception),
                                     "rollback record changed during verification")

    def test_private_rollback_record_rejects_short_read_and_masks_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollback.json"
            path.write_text(json.dumps(ready()), encoding="utf-8")
            path.chmod(0o600)
            original = os.fstat

            def same_inflated_length(fd):
                info = original(fd)
                fields = {
                    key: getattr(info, key)
                    for key in ("st_dev", "st_ino", "st_mode", "st_size",
                                "st_mtime_ns", "st_ctime_ns")
                }
                fields["st_size"] += 1
                return SimpleNamespace(**fields)

            output = io.StringIO()
            with patch.object(p.os, "fstat", side_effect=same_inflated_length):
                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()):
                    status = p.main(["check", str(path), "--from-sha",
                                     FROM_SHA, "--to-sha", TO_SHA])
            self.assertEqual(status, 1)
            self.assertEqual(output.getvalue().strip(),
                             "NO-GO: rollback record changed during verification")
            self.assertNotIn("synthetic-", output.getvalue())

    def test_symlink_fifo_directory_and_oversized_record_fail_without_blocking(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / "valid.json"
            target.write_text(json.dumps(ready()))
            target.chmod(0o600)
            symlink = root / "linked.json"
            try:
                symlink.symlink_to(target)
            except (OSError, NotImplementedError):
                pass
            else:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(symlink), "--from-sha",
                        FROM_SHA, "--to-sha", TO_SHA]), 0)
                    self.assertEqual(p.main(["init", "--from-sha", FROM_SHA,
                        "--to-sha", TO_SHA, "--output", str(symlink)]), 2)
                self.assertEqual(json.loads(target.read_text())["from_release_sha"], FROM_SHA)
            huge = root / "huge.json"
            huge.write_bytes(b" " * (p.MAX_ROLLBACK_RECORD_BYTES + 1))
            huge.chmod(0o600)
            with contextlib.redirect_stderr(io.StringIO()):
                for path in (huge, root):
                    self.assertNotEqual(p.main(["check", str(path), "--from-sha",
                        FROM_SHA, "--to-sha", TO_SHA]), 0)
            if hasattr(os, "mkfifo"):
                fifo = root / "pipe"
                os.mkfifo(fifo, 0o600)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(p.main(["check", str(fifo), "--from-sha",
                        FROM_SHA, "--to-sha", TO_SHA]), 0)


if __name__ == "__main__":
    unittest.main()
