"""Offline fail-closed tests for ephemeral two-runner synthetic recovery transport."""
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_cross_runner_transfer as t  # noqa: E402
from pilot_ci_lineage_reconcile import ALL_TABLES
from pilot_recovery_pair import observe

SHA = "a" * 40
ENV = {
    "APP_ENV": "test",
    "POSTGRES_DB": "mcri_performance",
    "POSTGRES_USER": "mcri_performance",
    "POSTGRES_PASSWORD": "".join(("synthetic", "-", "ci", "-", "never", "-", "real")),
    "MCRI_CI_RESTORE_PROBE": "1",
    "MCRI_CI_CROSS_RUNNER_EXPORT": "1",
    "MCRI_CI_CROSS_RUNNER_RESTORE": "1",
    "GITHUB_ACTIONS": "true",
}
REV = "0224_obs_refresh_recovery_anchor"
LINEAGE = {key: (1, "a" * 64) for key in ALL_TABLES}


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as tmp:
        previous = Path.cwd()
        try:
            os.chdir(tmp)
            root = Path("source")
            root.mkdir()
            dump = root / "synthetic.dump"
            archive = root / "synthetic-evidence.tar"
            manifest = root / "pair.json"
            dump.write_bytes(b"PGDMP-ci-only-bounded-synthetic")
            digest = hashlib.sha256(dump.read_bytes()).hexdigest()
            Path(str(dump) + ".sha256").write_text(digest + "  synthetic.dump\n")
            Path(str(dump) + ".meta").write_text(
                "format=mcri-postgres-backup-v1\n"
                "created_at_utc=2026-10-11T00:00:00Z\n"
                "database=mcri_performance\n"
                "git_sha=" + SHA + "\n"
                "alembic_heads=" + REV + "\n"
                "dump_file=synthetic.dump\n"
                "dump_sha256=" + digest + "\n"
            )
            with tarfile.open(archive, mode="w") as output:
                body = b"synthetic-evidence-only"
                member = tarfile.TarInfo("synthetic.pdf")
                member.size = len(body)
                output.addfile(member, BytesIO(body))
            manifest.write_text(json.dumps(observe(
                db_dump=dump, evidence_archive=archive,
                release_sha=SHA,
                quiescence_ref="synthetic-ci-compose-writers-stopped")))
            yield dump, archive, manifest
        finally:
            os.chdir(previous)


def export(dump, archive, manifest):
    t.export_pair(
        root=t.FIXED_TRANSFER, dump=dump, archive=archive, manifest=manifest,
        sha=SHA, claim_count="1", revision=REV,
        source_lineage=LINEAGE, env=ENV)


class CrossRunnerTransferTests(unittest.TestCase):
    def test_valid_export_is_exact_file_set_and_bound_to_release(self):
        with fixture() as (dump, archive, manifest):
            export(dump, archive, manifest)
            root = t.FIXED_TRANSFER
            self.assertEqual({p.name for p in root.iterdir()}, t.BASENAMES)
            t.pair_valid(root, SHA)
            self.assertEqual(t.validate_record(
                json.loads((root / "source-lineage.json").read_text()), SHA
            )["source_alembic_revision"], REV)
            self.assertNotIn(ENV["POSTGRES_PASSWORD"],
                             (root / "source-lineage.json").read_text())
            self.assertNotIn(ENV["POSTGRES_PASSWORD"],
                             (root / "pair.json").read_text())

    def test_second_runner_calls_real_restorer_and_never_claims_host_go(self):
        with fixture() as (dump, archive, manifest):
            export(dump, archive, manifest)
            with patch.object(t, "restore_and_verify", return_value={
                "separate_postgres_engine_restored": True,
                "isolated_container_network_disabled": True,
                "separate_engine_lineage_families_matched": 7,
                "separate_engine_documents_matched": 1,
                "pilot_authorized": False,
            }) as restore:
                result = t.verify(root=t.FIXED_TRANSFER, sha=SHA, env=ENV)
            args = restore.call_args.kwargs
            self.assertEqual(args["expected_claim_count"], "1")
            self.assertEqual(args["expected_revision"], REV)
            self.assertEqual(len(args["source_lineage"]), 7)
            self.assertTrue(result["github_actions_separate_job_restored"])
            for field in ("independent_physical_host_verified",
                          "customer_environment_restore_verified",
                          "atomic_external_storage_snapshot_verified",
                          "production_recovery_drill_verified", "pilot_authorized"):
                self.assertIs(result[field], False)

    def test_modified_archive_or_checksum_rejected_before_any_restore(self):
        for kind in ("archive", "dump", "sidecar", "extra-file"):
            with self.subTest(kind=kind), fixture() as (dump, archive, manifest):
                export(dump, archive, manifest)
                root = t.FIXED_TRANSFER
                if kind == "archive":
                    with (root / archive.name).open("ab") as target:
                        target.write(b"bad")
                elif kind == "dump":
                    with (root / dump.name).open("ab") as target:
                        target.write(b"bad")
                elif kind == "sidecar":
                    (root / "synthetic.dump.meta").write_text("not-matching")
                else:
                    (root / "unexpected.txt").write_text("unexpected")
                with patch.object(t, "restore_and_verify") as restore:
                    with self.assertRaises(t.CrossRunnerError):
                        t.verify(root=root, sha=SHA, env=ENV)
                    restore.assert_not_called()

    def test_changed_sha_and_source_lineage_record_fail_closed(self):
        with fixture() as (dump, archive, manifest):
            export(dump, archive, manifest)
            record_path = t.FIXED_TRANSFER / "source-lineage.json"
            record = json.loads(record_path.read_text())
            record["source_lineage"]["documents"] = [0, "a" * 64]
            record_path.write_text(json.dumps(record))
            with patch.object(t, "restore_and_verify") as restore:
                with self.assertRaises(t.CrossRunnerError):
                    t.verify(root=t.FIXED_TRANSFER, sha=SHA, env=ENV)
                restore.assert_not_called()
            with self.assertRaises(t.CrossRunnerError):
                t.pair_valid(t.FIXED_TRANSFER, "b" * 40)

    def test_synthetic_ci_markers_and_destination_required(self):
        with fixture() as (dump, archive, manifest):
            for field, value in (
                ("APP_ENV", "production"),
                ("MCRI_CI_CROSS_RUNNER_EXPORT", "0"),
                ("GITHUB_ACTIONS", "false"),
                ("POSTGRES_DB", "real-customer-db"),
            ):
                env = {**ENV, field: value}
                with self.subTest(field=field), self.assertRaises(t.CrossRunnerError):
                    t.export_pair(
                        root=t.FIXED_TRANSFER, dump=dump, archive=archive,
                        manifest=manifest, sha=SHA, claim_count="1",
                        revision=REV, source_lineage=LINEAGE, env=env)
                self.assertFalse(t.FIXED_TRANSFER.exists())
            with self.assertRaises(t.CrossRunnerError):
                t.export_pair(root=Path("other-output"), dump=dump,
                    archive=archive, manifest=manifest, sha=SHA,
                    claim_count="1", revision=REV,
                    source_lineage=LINEAGE, env=ENV)
            export(dump, archive, manifest)
            with self.assertRaises(t.CrossRunnerError):
                t.export_pair(root=t.FIXED_TRANSFER, dump=dump,
                    archive=archive, manifest=manifest, sha=SHA,
                    claim_count="1", revision=REV,
                    source_lineage=LINEAGE, env=ENV)

    def test_symlink_extraneous_or_missing_transfer_refused(self):
        with fixture() as (dump, archive, manifest):
            export(dump, archive, manifest)
            root = t.FIXED_TRANSFER
            (root / "synthetic.dump.meta").unlink()
            (root / "synthetic.dump.meta").symlink_to(
                (Path.cwd() / "source" / "synthetic.dump.meta"))
            with self.assertRaises(t.CrossRunnerError):
                t.pair_valid(root, SHA)

    def test_malformed_lineage_bounds_and_unknown_families_rejected(self):
        for modified in (
            {**LINEAGE, "unknown": (1, "a" * 64)},
            {**LINEAGE, "documents": (True, "a" * 64)},
            {**LINEAGE, "documents": (1, "not-a-hash")},
            {**LINEAGE, "documents": (10001, "a" * 64)},
        ):
            with self.assertRaises(t.CrossRunnerError):
                t.checked_lineage(modified)


if __name__ == "__main__":
    unittest.main()
