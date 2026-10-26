"""Private local byte-integrity regression with fictional tiny files only."""
import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.persian_ocr_local_source_integrity import main, verify_source_bytes
from scripts.tests.test_persian_ocr_blind_cohort_preflight import example_manifest


def small_study(root: Path):
    manifest = copy.deepcopy(example_manifest())
    files = []
    for idx, item in enumerate(manifest["sources"]):
        data = ("invented binary scan " + str(idx)).encode("utf-8")
        path = root / "fiction" / f"scan-{idx}.bin"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        item["source_file_sha256"] = hashlib.sha256(data).hexdigest()
        files.append({
            "case_ref": item["case_ref"],
            "relative_path": "fiction/" + path.name,
        })
    return manifest, {"schema_version": 1, "files": files}


class LocalSourceByteIntegrityTests(unittest.TestCase):
    def test_byte_hashes_match_but_never_claim_independent_provenance(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manifest, inventory = small_study(root)
            result = verify_source_bytes(manifest, inventory, root=root)
            self.assertTrue(result["local_source_hashes_matched"])
            self.assertEqual(result["registered_source_files"], 4)
            self.assertEqual(result["locally_hash_matched_source_files"], 4)
            self.assertEqual(result["development_source_files"], 1)
            self.assertEqual(result["holdout_source_files"], 3)
            self.assertGreater(result["source_bytes_read_total"], 0)
            for key in (
                "source_provenance_independently_attested",
                "customer_permission_verified",
                "blinding_independently_attested",
                "reference_transcripts_independently_adjudicated",
                "negation_scope_semantics_verified",
                "human_bilingual_review_completed",
                "pilot_accepted",
            ):
                self.assertFalse(result[key])
            self.assertNotIn("paths", result)
            self.assertNotIn("case_refs", result)

    def test_changed_missing_and_misbound_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manifest, inventory = small_study(root)
            corrupted = root / inventory["files"][1]["relative_path"]
            corrupted.write_bytes(b"tampered test bytes")
            with self.assertRaises(ValueError):
                verify_source_bytes(manifest, inventory, root=root)
            manifest, inventory = small_study(root)
            inventory["files"][1]["relative_path"] = inventory["files"][0]["relative_path"]
            with self.assertRaises(ValueError):
                verify_source_bytes(manifest, inventory, root=root)
            manifest, inventory = small_study(root)
            inventory["files"].pop()
            with self.assertRaises(ValueError):
                verify_source_bytes(manifest, inventory, root=root)
            manifest, inventory = small_study(root)
            inventory["files"][0]["case_ref"] = "NOT-REGISTERED"
            with self.assertRaises(ValueError):
                verify_source_bytes(manifest, inventory, root=root)
            manifest, inventory = small_study(root)
            (root / inventory["files"][0]["relative_path"]).unlink()
            with self.assertRaises(OSError):
                verify_source_bytes(manifest, inventory, root=root)

    def test_path_escape_symlink_and_nonregular_source_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manifest, inventory = small_study(root)
            for unsafe in (
                "../outside.png",
                "fiction/../../outside.png",
                "/etc/passwd",
                "fiction//scan-0.bin",
                "fiction/./scan-0.bin",
                "C:/fake.img",
                r"fiction\\scan-0.bin",
                "",
            ):
                modified = copy.deepcopy(inventory)
                modified["files"][0]["relative_path"] = unsafe
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    verify_source_bytes(manifest, modified, root=root)
            # Directory and direct symlink cannot be opened as evidence bytes.
            modified = copy.deepcopy(inventory)
            modified["files"][0]["relative_path"] = "fiction"
            with self.assertRaises(ValueError):
                verify_source_bytes(manifest, modified, root=root)
            shortcut = root / "fiction" / "alias.bin"
            try:
                shortcut.symlink_to(root / "fiction" / "scan-0.bin")
            except (OSError, NotImplementedError):
                pass
            else:
                modified["files"][0]["relative_path"] = "fiction/alias.bin"
                with self.assertRaises(ValueError):
                    verify_source_bytes(manifest, modified, root=root)
            # Intermediate directory symlink also denied, not followed.
            symlink_dir = root / "alias_dir"
            try:
                symlink_dir.symlink_to(root / "fiction", target_is_directory=True)
            except (OSError, NotImplementedError):
                pass
            else:
                modified["files"][0]["relative_path"] = "alias_dir/scan-0.bin"
                with self.assertRaises(ValueError):
                    verify_source_bytes(manifest, modified, root=root)

    def test_malformed_inventory_and_changed_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manifest, inventory = small_study(root)
            for invalid in (
                {"schema_version": True, "files": inventory["files"]},
                {"schema_version": 1, "files": [*inventory["files"], inventory["files"][0]]},
                {"schema_version": 1, "files": [{**inventory["files"][0], "approved": True}, *inventory["files"][1:]]},
                {"schema_version": 1, "files": [{**inventory["files"][0], "relative_path": 12}, *inventory["files"][1:]]},
            ):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    verify_source_bytes(manifest, invalid, root=root)
            modified = copy.deepcopy(manifest)
            modified["sources"][0]["source_file_sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                verify_source_bytes(modified, inventory, root=root)
            modified = copy.deepcopy(manifest)
            modified["sources"][0]["split"] = "not_predeclared"
            with self.assertRaises(ValueError):
                verify_source_bytes(modified, inventory, root=root)

    def test_cli_does_not_echo_path_hash_or_content_even_on_failure(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            manifest, inventory = small_study(root)
            a = root / "local_manifest.json"
            b = root / "local_file_inventory.json"
            a.write_text(json.dumps(manifest), encoding="utf-8")
            b.write_text(json.dumps(inventory), encoding="utf-8")
            for tamper in (False, True):
                if tamper:
                    (root / inventory["files"][2]["relative_path"]).write_bytes(b"SECRET scan source")
                out, err = StringIO(), StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(["--manifest", str(a), "--inventory", str(b), "--source-root", str(root)])
                self.assertEqual(code, 2 if tamper else 0)
                if tamper:
                    self.assertEqual(out.getvalue(), "")
                    self.assertEqual(err.getvalue().strip(), "ocr_source_integrity_rejected")
                else:
                    self.assertEqual(err.getvalue(), "")
                    self.assertTrue(json.loads(out.getvalue())["local_source_hashes_matched"])
                for private in ("DEVELOPMENT-ONLY", "FICTION-HM1", "scan-0.bin", str(root), "SECRET"):
                    self.assertNotIn(private, out.getvalue() + err.getvalue())
            # Reject a JSON object with duplicate keys, never silently override a file binding.
            a.write_text(a.read_text().replace(
                '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1
            ), encoding="utf-8")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--manifest", str(a), "--inventory", str(b), "--source-root", str(root)])
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "ocr_source_integrity_rejected")


if __name__ == "__main__":
    unittest.main()
