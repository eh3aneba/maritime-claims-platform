"""Offline bounded synthetic Evidence extraction + DB lineage validation."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_ci_evidence_restore import (  # noqa: E402
    EvidenceRestoreError, restore_and_reconcile, safe_relative,
)


def archive_fixture(path: Path, *, entries=None) -> bytes:
    files = entries if entries is not None else (
        ("documents/one.pdf", b"%PDF- synthetic demo 1"),
        ("documents/two.txt", b"harmless demo 2"),
    )
    with tarfile.open(path, mode="w") as tf:
        for name, content in files:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, BytesIO(content))
    return path.read_bytes()


def rows() -> str:
    value = b"%PDF- synthetic demo 1"
    return json.dumps([{"key": "documents/one.pdf", "sha256": hashlib.sha256(value).hexdigest(),
                        "size": len(value)}])


class EvidenceRestoreTests(unittest.TestCase):
    def test_extracts_into_new_temp_dir_and_matches_document_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "evidence.tar"
            archive_fixture(archive)
            restore = root / "isolated"
            restore.mkdir()
            out = restore_and_reconcile(archive, restore, rows())
            self.assertEqual(out, {"files_restored": 2, "demo_documents_matched": 1})
            self.assertEqual((restore / "documents/one.pdf").read_bytes(),
                             b"%PDF- synthetic demo 1")
            self.assertTrue((restore / "documents/two.txt").is_file())
            self.assertNotIn("documents/one.pdf", str(out))

    def test_missing_tampered_and_wrong_size_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "evidence.tar"
            archive_fixture(archive)
            valid = json.loads(rows())
            cases = [
                [{**valid[0], "sha256": "0" * 64}],
                [{**valid[0], "size": 1}],
                [{**valid[0], "key": "documents/missing.pdf"}],
                [],
                [valid[0], valid[0]],
            ]
            for i, data in enumerate(cases):
                restore = root / f"isolated-{i}"
                restore.mkdir()
                with self.assertRaises(EvidenceRestoreError):
                    restore_and_reconcile(archive, restore, json.dumps(data))

    def test_refuses_paths_links_duplicate_members_and_nonempty_target(self):
        for name, linked in (
            ("../escape", False), ("/absolute", False),
            ("one/../../escape", False), ("one//two", False),
            ("one\\two", False), ("one/./two", False),
            ("documents/symlink", True),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                archive = root / "data.tar"
                with tarfile.open(archive, mode="w") as tf:
                    info = tarfile.TarInfo(name)
                    if linked:
                        info.type = tarfile.SYMTYPE
                        info.linkname = "/secret"
                        tf.addfile(info)
                    else:
                        info.size = 1
                        tf.addfile(info, BytesIO(b"x"))
                restored = root / "isolated"
                restored.mkdir()
                with self.assertRaises(EvidenceRestoreError):
                    restore_and_reconcile(archive, restored, rows())
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "data.tar"
            archive_fixture(archive)
            recovered = root / "isolated"
            recovered.mkdir()
            (recovered / "existing").write_text("do not overwrite")
            with self.assertRaises(EvidenceRestoreError):
                restore_and_reconcile(archive, recovered, rows())

    def test_refuses_malformed_document_rows_and_unsafe_keys(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "data.tar"
            archive_fixture(archive)
            for i, bad in enumerate(('{"not":"array"}', "not-json",
                                    json.dumps([{"key":"../secret",
                                      "size":1,"sha256":"0"*64}]))):
                recovered = root / f"restore-{i}"
                recovered.mkdir()
                with self.assertRaises(EvidenceRestoreError):
                    restore_and_reconcile(archive, recovered, bad)
        for path in ("", "../escape", "/absolute", "a//b", "a/./b", "a\\b"):
            with self.assertRaises(EvidenceRestoreError):
                safe_relative(path)


if __name__ == "__main__":
    unittest.main()
