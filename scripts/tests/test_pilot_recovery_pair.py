"""Synthetic, offline regressions for Pilot DB/Evidence integrity pairing.

These tests do not claim a completed production restore or cross-store snapshot.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_recovery_pair import (  # noqa: E402
    RecoveryEvidenceError, check_record, main, observe,
)

SHA = "a" * 40
OTHER_SHA = "b" * 40


def fixtures(root: Path) -> tuple[Path, Path]:
    dump = root / "synthetic.dump"
    dump.write_bytes(b"PGDMP synthetic controlled bytes\n")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    Path(str(dump) + ".sha256").write_text(digest + "  synthetic.dump\n")
    Path(str(dump) + ".meta").write_text(
        "format=mcri-postgres-backup-v1\n"
        "created_at_utc=2026-10-10T03:00:00Z\n"
        "database=synthetic_pilot\n"
        f"git_sha={SHA}\n"
        "alembic_heads=0224_obs_refresh_recovery_anchor\n"
        "dump_file=synthetic.dump\n"
        f"dump_sha256={digest}\n"
    )
    archive = root / "evidence.tar"
    with tarfile.open(archive, mode="w") as tf:
        data = b"synthetic-only-evidence"
        item = tarfile.TarInfo("documents/a.pdf")
        item.size = len(data)
        tf.addfile(item, BytesIO(data))
    return dump, archive


class PilotRecoveryPairTests(unittest.TestCase):
    def test_creates_digest_bound_but_explicitly_no_go_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump, archive = fixtures(Path(tmp))
            record = observe(
                db_dump=dump, evidence_archive=archive,
                release_sha=SHA, quiescence_ref="change-20261010-001",
            )
            self.assertTrue(record["artifact_integrity_bound"])
            self.assertIs(record["same_recovery_point_verified"], False)
            self.assertIs(record["restore_drill_verified"], False)
            self.assertIs(record["pilot_authorized"], False)
            self.assertEqual(record["evidence"]["entry_count"], 1)
            self.assertEqual(record["release_sha"], SHA)
            self.assertEqual(record["evidence"]["archive_sha256"],
                hashlib.sha256(archive.read_bytes()).hexdigest())
            check_record(record, record, SHA)

    def test_db_sidecar_tamper_and_wrong_release_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump, archive = fixtures(Path(tmp))
            dump.write_bytes(b"tampered")
            with self.assertRaisesRegex(RecoveryEvidenceError, "checksum mismatch"):
                observe(db_dump=dump, evidence_archive=archive, release_sha=SHA,
                        quiescence_ref="change-001")
        with tempfile.TemporaryDirectory() as tmp:
            dump, archive = fixtures(Path(tmp))
            with self.assertRaisesRegex(RecoveryEvidenceError, "release or digest"):
                observe(db_dump=dump, evidence_archive=archive,
                        release_sha=OTHER_SHA, quiescence_ref="change-001")

    def test_evidence_file_mutation_rejected_on_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump, archive = fixtures(root)
            record = observe(db_dump=dump, evidence_archive=archive,
                             release_sha=SHA, quiescence_ref="change-001")
            with tarfile.open(archive, "w") as tf:
                data = b"new"
                item = tarfile.TarInfo("documents/a.pdf")
                item.size = len(data)
                tf.addfile(item, BytesIO(data))
            current = observe(db_dump=dump, evidence_archive=archive,
                              release_sha=SHA, quiescence_ref="change-001")
            with self.assertRaisesRegex(RecoveryEvidenceError, "binding differs"):
                check_record(record, current, SHA)

    def test_archive_rejects_traversal_links_duplicates_and_special(self):
        for name, kind in (
            ("../outside", "file"), ("/etc/passwd", "file"),
            ("evidence\\escape", "file"), ("evidence/link", "symlink"),
            ("evidence/device", "char"),
        ):
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                dump, archive = fixtures(root)
                with tarfile.open(archive, "w") as tf:
                    item = tarfile.TarInfo(name)
                    if kind == "symlink":
                        item.type = tarfile.SYMTYPE
                        item.linkname = "../../etc/passwd"
                    elif kind == "char":
                        item.type = tarfile.CHRTYPE
                    else:
                        item.size = 1
                    tf.addfile(item, BytesIO(b"x") if item.size else None)
                with self.assertRaises(RecoveryEvidenceError):
                    observe(db_dump=dump, evidence_archive=archive,
                            release_sha=SHA, quiescence_ref="change-001")
        with tempfile.TemporaryDirectory() as tmp:
            dump, archive = fixtures(Path(tmp))
            with tarfile.open(archive, "w") as tf:
                for _ in range(2):
                    item = tarfile.TarInfo("duplicate.txt")
                    item.size = 1
                    tf.addfile(item, BytesIO(b"x"))
            with self.assertRaisesRegex(RecoveryEvidenceError, "duplicate"):
                observe(db_dump=dump, evidence_archive=archive,
                        release_sha=SHA, quiescence_ref="change-001")

    def test_unsafe_quiescence_reference_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump, archive = fixtures(Path(tmp))
            for bad in ("", "../secret", "https://customer/", "x", "secret space"):
                with self.subTest(ref=bad), self.assertRaises(RecoveryEvidenceError):
                    observe(db_dump=dump, evidence_archive=archive,
                            release_sha=SHA, quiescence_ref=bad)

    def test_cli_exclusive_create_and_exact_content_reverify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dump, archive = fixtures(root)
            output = root / "pair.json"
            create = ["create", "--db-dump", str(dump),
                      "--evidence-archive", str(archive), "--release-sha", SHA,
                      "--quiescence-ref", "change-001", "--output", str(output)]
            verify = ["verify", "--db-dump", str(dump),
                      "--evidence-archive", str(archive), "--release-sha", SHA,
                      "--manifest", str(output)]
            self.assertEqual(main(create), 0)
            prior = output.read_bytes()
            self.assertEqual(main(create), 2)
            self.assertEqual(output.read_bytes(), prior)
            self.assertEqual(main(verify), 0)
            supplied = json.loads(prior)
            supplied["pilot_authorized"] = True
            output.write_text(json.dumps(supplied))
            self.assertEqual(main(verify), 2)


if __name__ == "__main__":
    unittest.main()
