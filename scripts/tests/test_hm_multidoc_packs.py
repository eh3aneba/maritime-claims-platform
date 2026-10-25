"""Regression contract for versioned, uploadable, invented H&M case packs."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from scripts import hm_multidoc_packs as fixtures


class HMCorpusTests(unittest.TestCase):
    def test_exact_six_development_holdout_and_document_version_lines(self):
        corpus = fixtures.load_corpus()
        self.assertEqual(corpus["corpus_version"], "1.0.0")
        self.assertIs(corpus["fictional"], True)
        self.assertIs(corpus["real_customer_data"], False)
        self.assertIs(corpus["approved_expert_reference_included"], False)
        self.assertEqual(
            [c["case_id"] for c in corpus["cases"]],
            [f"HM-{n:02d}" for n in range(1, 7)],
        )
        self.assertEqual(
            [c["dataset_split"] for c in corpus["cases"]],
            ["development"] * 4 + ["holdout"] * 2,
        )
        self.assertEqual([len(c["documents"]) for c in corpus["cases"]], [4, 4, 4, 5, 4, 4])
        self.assertTrue(all(c["currency"] == "USD" for c in corpus["cases"]))
        self.assertEqual(corpus["cases"][3]["documents"][-1]["replaces_source_id"], "engineer")
        self.assertEqual(corpus["cases"][3]["documents"][-1]["source_version"], 2)
        self.assertEqual(corpus["cases"][4]["documents"][1]["format"], "png")

    def test_render_real_valid_zip_xml_docx_for_each_text_document(self):
        corpus = fixtures.load_corpus()
        for case in corpus["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertEqual(len(fixtures.observed_source_digest(case)), 64)
                for doc in case["documents"]:
                    if doc["format"] == "png":
                        continue
                    payload, mime = fixtures.make_upload_bytes(doc)
                    self.assertTrue(payload.startswith(b"PK"))
                    self.assertEqual(mime, fixtures._MIME["docx"])
                    with ZipFile(BytesIO(payload)) as archive:
                        self.assertEqual(
                            set(archive.namelist()),
                            {"[Content_Types].xml", "_rels/.rels", "word/document.xml"},
                        )
                        root = ET.fromstring(archive.read("word/document.xml"))
                        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                        found = [element.text for element in root.findall(".//w:t", ns)]
                        self.assertEqual(found, doc["source_lines"])

    def test_no_scan_substituted_with_text_when_page_absent(self):
        doc = fixtures.load_corpus()["cases"][4]["documents"][1]
        with self.assertRaisesRegex(ValueError, "synthetic_scan_browser_required"):
            fixtures.make_upload_bytes(doc)

    def test_tampering_with_references_and_approval_flags_fails_closed(self):
        source = fixtures.load_corpus()
        for mode in ("approval", "extra", "missing", "bad_version", "bad_replacement", "holdout"):
            with self.subTest(mode=mode):
                bad = json.loads(json.dumps(source))
                if mode == "approval":
                    bad["approved_expert_reference_included"] = True
                elif mode == "extra":
                    bad["cases"].append(bad["cases"][0])
                elif mode == "missing":
                    bad["cases"][0]["documents"] = []
                elif mode == "bad_version":
                    bad["cases"][3]["documents"][-1]["source_version"] = 5
                elif mode == "bad_replacement":
                    bad["cases"][3]["documents"][-1]["replaces_source_id"] = "missing"
                else:
                    bad["cases"][4]["dataset_split"] = "development"
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "cases.json"
                    target.write_text(json.dumps(bad), encoding="utf-8")
                    with patch.object(fixtures, "CORPUS_PATH", target):
                        with self.assertRaises(ValueError):
                            fixtures.load_corpus()

    def test_source_and_reference_not_misrepresented_as_expert_ground_truth(self):
        corpus = fixtures.load_corpus()
        output = json.dumps(corpus)
        for unexpected in (
            '"expert_score"', '"expected_model_answer"', '"gold_label"',
            '"pilot_accepted"', '"expert_reference_approved"',
        ):
            self.assertNotIn(unexpected, output)
        self.assertIn("NOT SUPPLIED", output)
        self.assertIn("existence is unknown", output)
        self.assertIn("11:30 UTC", output)
        self.assertIn("11:55 UTC", output)
        self.assertIn("EUR 231000", output)


if __name__ == "__main__":
    unittest.main()
