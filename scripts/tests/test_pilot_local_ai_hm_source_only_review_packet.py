"""Static, local-only source-only H&M review packet regressions (no Ollama)."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import pilot_local_ai_hm_source_only_review_packet as packet

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/pilot_local_ai_hm_source_only_review_packet.py"
GUIDE = ROOT / "docs/operations/LOCAL_AI_HM_SOURCE_ONLY_REVIEW_PACKET.md"


class InventedHMSourceOnlyPacketTests(unittest.TestCase):
    def test_exact_three_cases_nine_invented_sources_and_blank_references(self):
        record = packet.fixed_blinded_source_review_packet()
        self.assertEqual(
            [case["scenario"] for case in record["cases"]],
            ["complete_records", "missing_engine_records", "conflicting_alarm_times"],
        )
        self.assertEqual(record["scope"], "invented_hm_source_only_blind_review_packet")
        self.assertEqual(record["packet_version"], "hm-invented-sources-v1")
        self.assertEqual(len(record["source_packet_sha256_observed"]), 64)
        self.assertFalse(record["includes_model_outputs"])
        self.assertFalse(record["includes_model_reference_candidate"])
        for flag in (
            "source_packet_digest_independently_attested",
            "contains_real_customer_evidence", "reviewer_blindness_verified",
            "independent_expert_labels_collected", "expert_reference_approved",
            "pilot_accepted",
        ):
            self.assertFalse(record[flag])
        for case in record["cases"]:
            self.assertEqual([s["source_id"] for s in case["source_records"]],
                             ["S1", "S2", "S3"])
            self.assertEqual(case["review_outcome"], "pending")
            self.assertFalse(case["expert_reference_approved"])
            self.assertGreaterEqual(len(case["unanswered_review_criteria"]), 7)
            for source in case["source_records"]:
                self.assertEqual(source["source_version"], "v1")
                self.assertTrue(source["invented_source_text"].startswith("Synthetic "))
                self.assertTrue(1 <= len(source["invented_source_text"]) <= 512)

    def test_source_text_is_available_without_ground_truth_or_model_answer(self):
        cases = packet.fixed_blinded_source_review_packet()["cases"]
        missing = cases[1]["source_records"][2]["invented_source_text"]
        self.assertIn("NOT BEEN SUPPLIED", missing)
        self.assertIn("existence is unknown", missing)
        engineer = cases[2]["source_records"][0]["invented_source_text"]
        workshop = cases[2]["source_records"][1]["invented_source_text"]
        self.assertIn("11:30", engineer)
        self.assertIn("11:55", workshop)
        serialized = json.dumps(cases)
        for forbidden in ("reference_match_count", "model_response",
                          "expected_answer", "assessor_approved",
                          "model_digest_attested", "coverage_approved"):
            self.assertNotIn(forbidden, serialized)

    def test_packet_digest_is_stable_and_changes_if_an_invented_source_changes(self):
        first = packet.fixed_blinded_source_review_packet()
        again = packet.fixed_blinded_source_review_packet()
        self.assertEqual(first, again)
        canonical = json.dumps(first["cases"], ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        self.assertEqual(first["source_packet_sha256_observed"],
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest())

        original = packet.synthetic_source_catalog

        def modified(name):
            sources = original(name)
            if name == "complete_records":
                sources["S1"]["body"] += " (invented amendment)"
            return sources

        with patch.object(packet, "synthetic_source_catalog", side_effect=modified):
            changed = packet.fixed_blinded_source_review_packet()
        self.assertNotEqual(first["source_packet_sha256_observed"],
                            changed["source_packet_sha256_observed"])

    def test_non_synthetic_source_drift_fails_closed(self):
        original = packet.synthetic_source_catalog

        def mutated(name):
            sources = original(name)
            if name == "missing_engine_records":
                sources["S2"]["body"] = "REAL PRIVATE CUSTOMER DOCUMENT"
            return sources

        with patch.object(packet, "synthetic_source_catalog", side_effect=mutated):
            with self.assertRaisesRegex(ValueError, "synthetic_source_catalog_drift"):
                packet.fixed_blinded_source_review_packet()

    def test_unknown_source_structure_fails_closed(self):
        original = packet.synthetic_source_catalog

        def mutated(name):
            sources = original(name)
            if name == "conflicting_alarm_times":
                sources["S4"] = sources["S3"]
            return sources

        with patch.object(packet, "synthetic_source_catalog", side_effect=mutated):
            with self.assertRaisesRegex(ValueError, "synthetic_source_catalog_drift"):
                packet.fixed_blinded_source_review_packet()

    def test_preapproved_or_faked_review_packet_is_rejected(self):
        real = packet.fixed_unfilled_expert_review_checklist
        def fake():
            data = real()
            data["cases"][1]["review_outcome"] = "approved"
            return data
        with patch.object(packet, "fixed_unfilled_expert_review_checklist", side_effect=fake):
            with self.assertRaisesRegex(ValueError, "untrusted_review_checklist"):
                packet.fixed_blinded_source_review_packet()

    def test_no_unknown_argument_can_create_a_packet(self):
        for argv in ([], ["--bad"], ["--print-invented-hm-source-only-packet", "path"],
                     ["--print-invented-hm-source-only-packet", "--approve"]):
            with self.subTest(argv=argv), patch("builtins.print") as emit:
                self.assertEqual(packet.main(argv), 2)
                emit.assert_called_once_with(
                    "synthetic_source_packet_explicit_opt_in_required"
                )

    def test_manual_cli_prints_only_invented_data_without_any_approval(self):
        with patch("builtins.print") as emit:
            self.assertEqual(packet.main(["--print-invented-hm-source-only-packet"]), 0)
        result = json.loads(emit.call_args.args[0])
        self.assertEqual(len(result["cases"]), 3)
        self.assertFalse(result["expert_reference_approved"])
        self.assertIn("Synthetic ", emit.call_args.args[0])

    def test_unexpected_errors_do_not_echo_private_text(self):
        with patch.object(packet, "synthetic_source_catalog",
                          side_effect=RuntimeError("PRIVATE-ERROR")):
            with patch("builtins.print") as emit:
                self.assertEqual(packet.main(["--print-invented-hm-source-only-packet"]), 1)
                emit.assert_called_once_with("synthetic_source_packet_unavailable")

    def test_policy_no_arbitrary_io_or_inference_and_documentation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("http.client", "requests.", "OpenAI(", "subprocess",
                          "get_ai_provider(", "open(", "read_text(", "write_text(",
                          "DATABASE_URL", "customer_document_loader", "model.generate("):
            self.assertNotIn(forbidden, source)
        guide = GUIDE.read_text(encoding="utf-8")
        for required in ("--print-invented-hm-source-only-packet",
                         "blind", "independent H&M", "Pilot GO=NO",
                         "no model-generated"):
            self.assertIn(required, guide)


if __name__ == "__main__":
    unittest.main()
