"""Strict no-network, no-human-approval tests for synthetic H&M expert checklist."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from scripts import pilot_local_ai_hm_expert_review_checklist as checklist

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scripts/pilot_local_ai_hm_expert_review_checklist.py"
GUIDE = ROOT / "docs/operations/LOCAL_AI_HM_INDEPENDENT_EXPERT_REVIEW.md"


class IndependentHMExpertChecklistTests(unittest.TestCase):
    def test_fixed_exactly_three_scenarios_and_pending_only(self):
        record = checklist.fixed_unfilled_expert_review_checklist()
        self.assertEqual(record["scope"], "synthetic_expert_review_planning_only")
        self.assertEqual(
            [r["scenario"] for r in record["cases"]],
            ["complete_records", "missing_engine_records", "conflicting_alarm_times"],
        )
        for row in record["cases"]:
            self.assertEqual(row["source_record_ids"], ["S1", "S2", "S3"])
            self.assertGreaterEqual(len(row["criteria"]), 7)
            self.assertEqual(len(row["criteria"]), len(set(row["criteria"])))
            self.assertEqual(row["review_outcome"], "pending")
            for key in (
                "independent_expert_assigned",
                "independent_expert_labels_collected",
                "independent_expert_adjudication_completed",
            ):
                self.assertIs(row[key], False)
        for key in (
            "blinded_review_process_verified", "real_model_outputs_reviewed",
            "reviewer_identity_attested", "expert_reference_approved",
            "customer_evidence_reviewed", "pilot_accepted",
        ):
            self.assertIs(record[key], False)
        dump = json.dumps(record)
        for prohibited in (
            "Turbocharger damage", "11:30", "11:55",
            "NOT BEEN SUPPLIED", "negligence was", "model_digest",
            "reviewer_email", "customer_id",
        ):
            self.assertNotIn(prohibited, dump)

    def test_distinctions_for_missing_and_conflicting_records(self):
        cases = checklist.fixed_unfilled_expert_review_checklist()["cases"]
        missing = cases[1]["criteria"]
        conflict = cases[2]["criteria"]
        self.assertIn("not_supplied_not_mistaken_for_nonexistent", missing)
        self.assertIn("unknown_document_existence_preserved", missing)
        self.assertIn("both_reported_alarm_times_separately_attributed", conflict)
        self.assertIn("unresolved_conflict_not_silently_resolved", conflict)

    def test_repeated_calls_return_unfilled_independent_copies(self):
        a = checklist.fixed_unfilled_expert_review_checklist()
        a["cases"][0]["review_outcome"] = "approved"
        a["cases"][1]["criteria"].append("FAKE-APPROVAL")
        b = checklist.fixed_unfilled_expert_review_checklist()
        self.assertEqual(b["cases"][0]["review_outcome"], "pending")
        self.assertNotIn("FAKE-APPROVAL", b["cases"][1]["criteria"])

    def test_unknown_inputs_refuse_without_exposing_data(self):
        for args in (
            [], ["--wrong"],
            ["--print-unfilled-synthetic-hm-expert-checklist", "customer-file"],
            ["--print-unfilled-synthetic-hm-expert-checklist", "--approved"],
        ):
            with self.subTest(args=args), patch("builtins.print") as emit:
                self.assertEqual(checklist.main(args), 2)
                emit.assert_called_once_with(
                    "synthetic_expert_review_explicit_opt_in_required"
                )

    def test_explicit_flag_emits_pending_only(self):
        with patch("builtins.print") as emit:
            self.assertEqual(
                checklist.main(["--print-unfilled-synthetic-hm-expert-checklist"]), 0
            )
            data = json.loads(emit.call_args.args[0])
            self.assertEqual(len(data["cases"]), 3)
            self.assertFalse(data["pilot_accepted"])
            self.assertFalse(data["expert_reference_approved"])

    def test_unexpected_error_is_sanitized(self):
        with patch.object(checklist, "fixed_unfilled_expert_review_checklist",
                          side_effect=RuntimeError("PRIVATE-LOCAL-ERROR")):
            with patch("builtins.print") as emit:
                self.assertEqual(
                    checklist.main(["--print-unfilled-synthetic-hm-expert-checklist"]), 1
                )
                emit.assert_called_once_with(
                    "synthetic_expert_review_checklist_unavailable"
                )

    def test_module_has_no_io_dynamic_execution_or_source_text(self):
        source = SRC.read_text(encoding="utf-8")
        for term in (
            "http.client", "requests.", "OpenAI(", "get_ai_provider(",
            "open(", "read_text(", "write_text(", "subprocess",
            "DATABASE_URL", "customer_Evidence", "model.generate(",
        ):
            self.assertNotIn(term, source)
        guide = GUIDE.read_text(encoding="utf-8")
        for term in (
            "--print-unfilled-synthetic-hm-expert-checklist",
            "independent H&M", "blind", "Pilot GO=NO",
        ):
            self.assertIn(term, guide)


if __name__ == "__main__":
    unittest.main()
