"""Offline non-approving neutral phase-one expert packet regressions."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import pilot_local_ai_hm_neutral_blind_packet as blind

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/pilot_local_ai_hm_neutral_blind_packet.py"
DOC = ROOT / "docs/operations/LOCAL_AI_HM_NEUTRAL_BLIND_PHASE_ONE.md"


class NeutralBlindHMPacketTests(unittest.TestCase):
    def test_three_unlabeled_cases_no_reference_leakage_and_no_approval(self):
        data = blind.fixed_neutral_blind_hm_phase_one_packet()
        self.assertEqual(data["scope"], "invented_hm_neutral_blind_phase_one_only")
        self.assertEqual(data["packet_version"], "hm-neutral-phase-one-v1")
        self.assertEqual(
            [case["case_code"] for case in data["cases"]],
            ["CASE-01", "CASE-02", "CASE-03"],
        )
        self.assertEqual(len(data["review_questions"]), 4)
        self.assertEqual(len(data["packet_sha256_observed"]), 64)
        self.assertEqual([len(c["source_records"]) for c in data["cases"]], [3] * 3)
        for flag in (
            "digest_independently_attested", "reviewer_blindness_verified",
            "expert_labels_collected", "model_outputs_included",
            "baseline_answers_included", "review_completed", "pilot_accepted",
        ):
            self.assertIs(data[flag], False)
        serialized = json.dumps(data)
        for forbidden in (
            "complete_records", "missing_engine_records",
            "conflicting_alarm_times", "unanswered_review_criteria",
            "context_pairs", "critical_literal_requirements",
            "reference_match_count", "expected_answer", "review_outcome",
            "source_quotes_accepted_for_human_review", "model_response",
        ):
            self.assertNotIn(forbidden, serialized)
        for case in data["cases"]:
            self.assertEqual(
                [s["source_id"] for s in case["source_records"]],
                ["S1", "S2", "S3"],
            )
            self.assertTrue(all(
                s["invented_source_text"].startswith("Synthetic ")
                for s in case["source_records"]
            ))
        self.assertIn("existence is unknown", serialized)
        self.assertIn("11:55", serialized)

    def test_neutral_digest_is_stable_but_not_attested(self):
        first = blind.fixed_neutral_blind_hm_phase_one_packet()
        self.assertEqual(first, blind.fixed_neutral_blind_hm_phase_one_packet())
        canonical = json.dumps(
            {"cases": first["cases"],
             "review_questions": tuple(first["review_questions"])},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        self.assertEqual(
            first["packet_sha256_observed"],
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        self.assertIs(first["digest_independently_attested"], False)

    def test_source_packet_drift_and_approval_forgery_fail_closed(self):
        orig = blind.fixed_blinded_source_review_packet
        for form in ("bad_hash", "bad_source", "approved", "scenario_replaced", "extra_source"):
            with self.subTest(form=form):
                packet = orig()
                if form == "bad_hash":
                    packet["source_packet_sha256_observed"] = "0" * 64
                elif form == "bad_source":
                    packet["cases"][0]["source_records"][0]["invented_source_text"] = (
                        "REAL CUSTOMER CONTENT"
                    )
                elif form == "approved":
                    packet["expert_reference_approved"] = True
                elif form == "scenario_replaced":
                    packet["cases"][1]["scenario"] = "real_claim"
                else:
                    packet["cases"][0]["source_records"].append(
                        dict(packet["cases"][0]["source_records"][0])
                    )
                with patch.object(blind, "fixed_blinded_source_review_packet", return_value=packet):
                    with self.assertRaisesRegex(ValueError, "^untrusted_neutral_source_packet$"):
                        blind.fixed_neutral_blind_hm_phase_one_packet()

    def test_cli_requires_exact_opt_in_and_never_prints_candidate(self):
        for args in ([], ["--bad"], ["--print-neutral-blind-synthetic-hm-phase-one", "claim"]):
            with self.subTest(args=args), patch("builtins.print") as emit:
                self.assertEqual(blind.main(args), 2)
                emit.assert_called_once_with(
                    "neutral_blind_synthetic_hm_explicit_opt_in_required"
                )
        with patch("builtins.print") as emit:
            self.assertEqual(blind.main(["--print-neutral-blind-synthetic-hm-phase-one"]), 0)
        raw = emit.call_args.args[0]
        self.assertEqual(len(json.loads(raw)["cases"]), 3)
        self.assertNotIn("critical_literal", raw)

    def test_errors_do_not_echo_untrusted_source(self):
        with patch.object(blind, "fixed_blinded_source_review_packet",
                          side_effect=RuntimeError("PRIVATE-ERROR-FROM-SOURCE")):
            with patch("builtins.print") as emit:
                self.assertEqual(blind.main(["--print-neutral-blind-synthetic-hm-phase-one"]), 1)
                emit.assert_called_once_with("neutral_blind_synthetic_hm_packet_unavailable")

    def test_no_external_io_and_clear_nonapproval_runbook(self):
        src = SCRIPT.read_text(encoding="utf-8")
        imports = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertEqual(imports, {
            "__future__", "hashlib", "json", "sys", "typing",
            "scripts.pilot_local_ai_hm_fixture_matrix",
            "scripts.pilot_local_ai_hm_source_only_review_packet",
        })
        for unsafe in (
            "requests", "urllib", "subprocess", "http.client",
            "open(", "write_text(", "read_text(", "model.generate(",
            "DATABASE_URL", "OpenAI(", "get_ai_provider(",
        ):
            self.assertNotIn(unsafe, src)
        doc = DOC.read_text(encoding="utf-8")
        for keyword in ("CASE-01", "blind", "Pilot GO=NO", "independent",
                        "--print-neutral-blind-synthetic-hm-phase-one"):
            self.assertIn(keyword, doc)


if __name__ == "__main__":
    unittest.main()
