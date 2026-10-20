"""Offline fail-closed policies for mandatory synthetic H&M quote coverage."""
from pathlib import Path
import ast
import unittest

from scripts.pilot_local_ai_hm_fixture_matrix import (
    deterministic_reference_candidate, scenario_names,
)
from scripts.pilot_local_ai_hm_critical_quote_coverage import (
    _REQUIRED_LITERAL_QUOTES, observe_required_literal_quote_coverage,
)
from scripts.pilot_local_ai_source_gate import LocalAISourceGateError

ROOT = Path(__file__).resolve().parents[2]


class SyntheticHMCriticalQuoteCoverageTests(unittest.TestCase):
    def test_full_reference_has_all_required_literal_anchors(self):
        self.assertEqual(set(_REQUIRED_LITERAL_QUOTES), set(scenario_names()))
        for scenario in scenario_names():
            with self.subTest(scenario=scenario):
                result = observe_required_literal_quote_coverage(
                    scenario, deterministic_reference_candidate(scenario),
                )
                self.assertTrue(result["critical_literal_coverage_observed"])
                self.assertEqual(result["critical_literal_requirements_missing"], 0)
                self.assertGreaterEqual(result["critical_literal_requirements_total"], 3)
                self.assertFalse(result["expert_ground_truth_approved"])
                self.assertFalse(result["semantic_claims_verified"])
                self.assertFalse(result["pilot_accepted"])

    def test_source_backed_cherry_picking_must_not_count_as_complete(self):
        for scenario in scenario_names():
            with self.subTest(scenario=scenario):
                candidate = deterministic_reference_candidate(scenario)
                candidate["items"] = candidate["items"][:1]
                result = observe_required_literal_quote_coverage(scenario, candidate)
                self.assertFalse(result["critical_literal_coverage_observed"])
                self.assertGreater(result["critical_literal_requirements_missing"], 0)

    def test_missing_records_need_both_nonexistence_disclaimer_and_missing_status(self):
        candidate = deterministic_reference_candidate("missing_engine_records")
        candidate["items"][2]["verbatim_excerpt"] = (
            "Synthetic intake: Engine logs for the previous ten days"
        )
        report = observe_required_literal_quote_coverage("missing_engine_records", candidate)
        self.assertFalse(report["critical_literal_coverage_observed"])
        self.assertEqual(report["critical_literal_requirements_missing"], 2)
        self.assertNotIn("NOT BEEN SUPPLIED", str(report))

    def test_conflicting_times_require_distinct_sources(self):
        candidate = deterministic_reference_candidate("conflicting_alarm_times")
        candidate["items"] = [item for item in candidate["items"] if item["source_id"] != "S2"]
        report = observe_required_literal_quote_coverage("conflicting_alarm_times", candidate)
        self.assertFalse(report["critical_literal_coverage_observed"])
        self.assertEqual(report["critical_literal_requirements_missing"], 1)

    def test_unsupported_quotes_still_reject_before_coverage(self):
        candidate = deterministic_reference_candidate("missing_engine_records")
        candidate["items"][0]["verbatim_excerpt"] = "Vessel operator admitted negligence."
        with self.assertRaisesRegex(LocalAISourceGateError, "unsupported_quote"):
            observe_required_literal_quote_coverage("missing_engine_records", candidate)

    def test_no_network_file_io_or_runtime_model_imports_in_pure_observer(self):
        source = (ROOT / "scripts/pilot_local_ai_hm_critical_quote_coverage.py").read_text(encoding="utf-8")
        modules = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {"__future__", "scripts.pilot_local_ai_hm_fixture_matrix"})
        for term in ("HTTPConnection(", "open(", "write_text(", "subprocess", "requests", "get_ai_provider(", "model.generate("):
            self.assertNotIn(term, source)


if __name__ == "__main__":
    unittest.main()
