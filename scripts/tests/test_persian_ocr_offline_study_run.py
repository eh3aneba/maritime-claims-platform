"""Invented-only composed local study checks; never a human acceptance test."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.persian_ocr_offline_study_run import evaluate_study_packet, main
from scripts.tests.test_persian_ocr_local_source_integrity import small_study
from scripts.tests.test_persian_ocr_local_validation_metrics import example_study
from scripts.tests.test_persian_ocr_review_disagreement_metrics import fake_reviews


def bundled_study(root: Path):
    manifest, inventory = small_study(root)
    measurements = example_study()
    hashes = {item["case_ref"]: item["source_file_sha256"] for item in manifest["sources"]}
    for page in measurements["records"]:
        page["source_file_sha256"] = hashes[page["case_ref"]]
    return manifest, inventory, measurements


class ComposedPersianOcrStudyTests(unittest.TestCase):
    def test_local_packet_has_counts_no_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, study = bundled_study(root)
            packet = evaluate_study_packet(
                manifest=manifest, inventory=inventory, measurements=study, root=root
            )
            self.assertEqual(packet["measurement_kind"], "local_composed_descriptive_study_only")
            self.assertEqual(
                packet["source_file_hash_verification"]["locally_hash_matched_source_files"], 4
            )
            self.assertTrue(packet["blind_cohort_metadata"]["self_reported_cohort_structure_complete"])
            self.assertEqual(packet["literal_metrics"]["overall"]["ocr_exact_missing"], 1)
            self.assertEqual(packet["literal_metrics"]["overall"]["search_exact_missing"], 1)
            self.assertEqual(packet["literal_metrics"]["overall"]["ocr_positive_unknown"], 1)
            for key in (
                "source_provenance_independently_attested",
                "customer_permission_verified",
                "blinding_independently_attested",
                "reference_transcripts_independently_adjudicated",
                "human_bilingual_review_completed",
                "negation_scope_semantics_verified",
                "acceptance_thresholds_approved",
                "critical_fact_authorization_granted",
                "pilot_accepted",
            ):
                self.assertFalse(packet[key])
            dumped = json.dumps(packet, ensure_ascii=False)
            for marker in ("FICTION-HM1", "توربوشارژر", "نیست", "scan-0.bin", str(root)):
                self.assertNotIn(marker, dumped)

    def test_short_and_mismatched_studies_fail_closed_without_partial_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, study = bundled_study(root)
            incomplete = copy.deepcopy(study)
            incomplete["records"].pop()
            with self.assertRaises(ValueError):
                evaluate_study_packet(
                    manifest=manifest, inventory=inventory,
                    measurements=incomplete, root=root,
                )
            changed = copy.deepcopy(study)
            changed["records"][0]["source_file_sha256"] = "f" * 64
            with self.assertRaises(ValueError):
                evaluate_study_packet(
                    manifest=manifest, inventory=inventory,
                    measurements=changed, root=root,
                )
            (root / inventory["files"][0]["relative_path"]).write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                evaluate_study_packet(
                    manifest=manifest, inventory=inventory,
                    measurements=study, root=root,
                )

    def test_optional_review_rows_are_descriptive_and_never_human_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, study = bundled_study(root)
            reviews = fake_reviews()
            hashes = {
                source["case_ref"]: source["source_file_sha256"]
                for source in manifest["sources"]
            }
            for row in reviews["rows"]:
                row["source_file_sha256"] = hashes[row["case_ref"]]
            packet = evaluate_study_packet(
                manifest=manifest, inventory=inventory,
                measurements=study, root=root, reviews=reviews,
            )
            self.assertFalse(packet["submitted_review_rows_structurally_complete"])
            self.assertFalse(packet["independent_human_signoff_granted"])
            self.assertFalse(packet["human_bilingual_review_completed"])
            self.assertFalse(packet["pilot_accepted"])
            observations = packet["self_reported_reviewer_observations"]
            self.assertEqual(observations["overall"]["reviewers_disagreed"], 1)
            self.assertEqual(
                observations["overall"]["reference_spans_with_no_review_row"], 1
            )
            self.assertEqual(
                observations["overall"]["specialist_adjudication_record_missing"], 1
            )
            self.assertFalse(observations["reviewer_identity_independently_verified"])
            raw = json.dumps(packet, ensure_ascii=False)
            for secret in ("PSEUDO-A", "PSEUDO-C", "FICTION-HM1", "نیست", str(root)):
                self.assertNotIn(secret, raw)

            changed = copy.deepcopy(reviews)
            changed["rows"][0]["extraction_sha256"] = "f" * 64
            with self.assertRaises(ValueError):
                evaluate_study_packet(
                    manifest=manifest, inventory=inventory,
                    measurements=study, root=root, reviews=changed,
                )
            changed = copy.deepcopy(reviews)
            changed["rows"][0]["reviewer_two"]["reviewer_ref"] = "PSEUDO-A"
            with self.assertRaises(ValueError):
                evaluate_study_packet(
                    manifest=manifest, inventory=inventory,
                    measurements=study, root=root, reviews=changed,
                )

    def test_optional_review_cli_fails_closed_without_leaking_source_or_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, study = bundled_study(root)
            reviews = fake_reviews()
            hashes = {
                source["case_ref"]: source["source_file_sha256"]
                for source in manifest["sources"]
            }
            for row in reviews["rows"]:
                row["source_file_sha256"] = hashes[row["case_ref"]]
            paths = [
                root / name for name in (
                    "private_manifest.json", "private_inventory.json",
                    "private_study.json", "private_reviews.json",
                )
            ]
            for path, obj in zip(paths, (manifest, inventory, study, reviews)):
                path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            args = [
                "--manifest", str(paths[0]), "--inventory", str(paths[1]),
                "--measurements", str(paths[2]), "--source-root", str(root),
                "--reviews", str(paths[3]),
            ]
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(args)
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            result = json.loads(stdout.getvalue())
            self.assertEqual(
                result["self_reported_reviewer_observations"]["overall"]["reviewers_disagreed"],
                1,
            )
            self.assertFalse(result["pilot_accepted"])
            paths[3].write_text(
                paths[3].read_text(encoding="utf-8").replace(
                    '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1
                ), encoding="utf-8",
            )
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(args)
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(
                stderr.getvalue().strip(), "ocr_offline_study_packet_rejected"
            )
            for secret in ("PSEUDO-A", "FICTION-HM1", "نیست", str(root)):
                self.assertNotIn(secret, stdout.getvalue() + stderr.getvalue())


    def test_cli_writes_only_full_aggregate_or_generic_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest, inventory, study = bundled_study(root)
            paths = [root / x for x in ("private_manifest.json", "private_inventory.json", "private_study.json")]
            for path, obj in zip(paths, (manifest, inventory, study)):
                path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            argv = [
                "--manifest", str(paths[0]),
                "--inventory", str(paths[1]),
                "--measurements", str(paths[2]),
                "--source-root", str(root),
            ]
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), "")
            value = json.loads(out.getvalue())
            self.assertFalse(value["pilot_accepted"])
            self.assertEqual(value["literal_metrics"]["pages_measured_or_screened"], 3)
            for marker in ("FICTION-HM1", "توربوشارژر", "نیست", "scan-0.bin", str(root)):
                self.assertNotIn(marker, out.getvalue() + err.getvalue())
            # A malformed private annotation never causes traceback or source disclosure.
            paths[2].write_text(paths[2].read_text(encoding="utf-8").replace(
                '"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1
            ), encoding="utf-8")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue().strip(), "ocr_offline_study_packet_rejected")


if __name__ == "__main__":
    unittest.main()
