"""Offline fail-closed tests for guarded Protect main Admin-only activation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ruleset_admin_activation as gate  # noqa: E402
from pilot_ruleset_evidence import EXPECTED_CONTEXTS  # noqa: E402

SHA = "a" * 40
PR = 704


def sample():
    detail = {
        "id": gate.RULESET_ID,
        "name": "Protect main",
        "source": gate.REPO,
        "source_type": "Repository",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        },
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "allowed_merge_methods": ["squash"],
                    "required_review_thread_resolution": True,
                    "require_extra_approval_for_unattributed_changes": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": name} for name in sorted(gate.ORIGINAL)
                    ],
                },
            },
        ],
    }
    listed = [{
        "id": gate.RULESET_ID,
        "name": "Protect main",
        "source": gate.REPO,
        "source_type": "Repository",
    }]
    check_record = {
        "repository": gate.REPO,
        "all_required_checks_green": True,
        "exact_name_contexts_present": 11,
        "expected_checks": {
            name: {"outcome": "pass", "check_run_id": i + 1}
            for i, name in enumerate(sorted(EXPECTED_CONTEXTS))
        },
    }
    return listed, detail, check_record


class RulesetAdminActivationTests(unittest.TestCase):
    def test_only_seven_contexts_added_every_other_setting_intact(self):
        listed, detail, checks = sample()
        before = deepcopy(detail)
        payload = gate.make_proposal(listed, detail, checks)
        self.assertEqual(detail, before)
        self.assertEqual(set(payload), {
            "name", "target", "enforcement", "bypass_actors",
            "conditions", "rules",
        })
        self.assertEqual(payload["bypass_actors"], [])
        self.assertEqual(payload["conditions"], before["conditions"])
        original = next(x for x in before["rules"]
                        if x["type"] == "required_status_checks")
        new_rule = next(x for x in payload["rules"]
                        if x["type"] == "required_status_checks")
        self.assertEqual(
            {x["context"] for x in new_rule["parameters"]["required_status_checks"]},
            EXPECTED_CONTEXTS,
        )
        self.assertEqual(
            new_rule["parameters"]["strict_required_status_checks_policy"],
            original["parameters"]["strict_required_status_checks_policy"],
        )
        self.assertEqual(len(new_rule["parameters"]["required_status_checks"]), 11)

    def test_refuses_unsafe_ruleset_and_unexpected_baseline(self):
        for mutation in (
            lambda x: x.update(enforcement="evaluate"),
            lambda x: x.update(bypass_actors=[{"actor_id": 1}]),
            lambda x: x["rules"][3]["parameters"].update(
                allowed_merge_methods=["merge", "squash"]
            ),
            lambda x: x["rules"][4]["parameters"].update(
                strict_required_status_checks_policy=False
            ),
            lambda x: x["rules"][4]["parameters"]["required_status_checks"].append(
                {"context": "Unapproved gate"}
            ),
            lambda x: x["rules"][4]["parameters"]["required_status_checks"].pop(),
        ):
            listed, detail, checks = sample()
            mutation(detail)
            with self.assertRaises(gate.ActivationError):
                gate.make_proposal(listed, detail, checks)

    def test_refuses_missing_or_skipped_or_duplicate_preflight(self):
        for mutation in (
            lambda x: x.update(all_required_checks_green=False),
            lambda x: x["expected_checks"]["Backend tests"].update(
                outcome="not_pass"
            ),
            lambda x: x["expected_checks"].pop("Backend tests"),
            lambda x: x.update(repository="another/repo"),
        ):
            listed, detail, checks = sample()
            mutation(checks)
            with self.assertRaises(gate.ActivationError):
                gate.make_proposal(listed, detail, checks)

    def test_preview_never_writes_and_always_no_go(self):
        listed, detail, record = sample()
        with patch.object(gate, "fetch_checks", return_value=({}, [])), \
             patch.object(gate, "evaluate_checks", return_value=record), \
             patch.object(gate, "fetch_ruleset", return_value=(listed, detail)), \
             patch.object(gate, "_write_ruleset") as writing:
            evidence = gate.execute(
                pr=PR, sha=SHA, apply=False,
                ticket=None, confirmed_id=None, token=None,
            )
        writing.assert_not_called()
        self.assertFalse(evidence["ruleset_update_sent"])
        self.assertEqual(evidence["current_required_checks"], 4)
        self.assertFalse(evidence["customer_pilot_authorized"])
        self.assertFalse(evidence["deliberate_failed_required_check_merge_refusal_proven"])

    def test_apply_requires_exact_admin_acknowledgement(self):
        for ticket, confirmed in (
            (None, gate.RULESET_ID),
            ("ticket://approved-change", None),
            ("ticket://approved-change", gate.RULESET_ID + 1),
            ("some-raw-secret", gate.RULESET_ID),
        ):
            with self.assertRaises(gate.ActivationError):
                gate.execute(
                    pr=PR, sha=SHA, apply=True,
                    ticket=ticket, confirmed_id=confirmed, token="dummy",
                )

    def test_apply_readback_and_negative_proof_never_inferred(self):
        listed, detail, record = sample()
        complete = deepcopy(detail)
        updated = next(x for x in complete["rules"]
                       if x["type"] == "required_status_checks")
        updated["parameters"]["required_status_checks"] = [
            {"context": x} for x in sorted(EXPECTED_CONTEXTS)
        ]
        with patch.object(gate, "fetch_checks", return_value=({}, [])), \
             patch.object(gate, "evaluate_checks", return_value=record), \
             patch.object(gate, "fetch_ruleset", side_effect=[
                 (listed, detail), (listed, deepcopy(detail)), (listed, complete)
             ]), patch.object(gate, "_write_ruleset") as writing:
            evidence = gate.execute(
                pr=PR, sha=SHA, apply=True,
                ticket="ticket://approved-change", confirmed_id=gate.RULESET_ID,
                token="dummy",
            )
        writing.assert_called_once()
        self.assertEqual(evidence["current_required_checks"], 11)
        self.assertTrue(evidence["eleven_check_ruleset_readback_confirmed"])
        self.assertFalse(evidence["deliberate_failed_required_check_merge_refusal_proven"])
        self.assertFalse(evidence["customer_pilot_authorized"])

    def test_pre_write_drift_rejects_mutation(self):
        listed, detail, record = sample()
        drift = deepcopy(detail)
        drift["rules"][3]["parameters"]["required_approving_review_count"] = 1
        with patch.object(gate, "fetch_checks", return_value=({}, [])), \
             patch.object(gate, "evaluate_checks", return_value=record), \
             patch.object(gate, "fetch_ruleset",
                          side_effect=[(listed, detail), (listed, drift)]), \
             patch.object(gate, "_write_ruleset") as writing:
            with self.assertRaises(gate.ActivationError):
                gate.execute(
                    pr=PR, sha=SHA, apply=True,
                    ticket="ticket://approved-change",
                    confirmed_id=gate.RULESET_ID, token="dummy",
                )
        writing.assert_not_called()

    def test_put_failure_never_claims_approval_or_degrades_safeguards(self):
        listed, detail, record = sample()
        with patch.object(gate, "fetch_checks", return_value=({}, [])), \
             patch.object(gate, "evaluate_checks", return_value=record), \
             patch.object(gate, "fetch_ruleset", return_value=(listed, detail)), \
             patch.object(gate, "_write_ruleset",
                          side_effect=gate.ActivationError("not accepted")):
            with self.assertRaises(gate.ActivationError):
                gate.execute(
                    pr=PR, sha=SHA, apply=True,
                    ticket="ticket://approved-change",
                    confirmed_id=gate.RULESET_ID, token="dummy",
                )


if __name__ == "__main__":
    unittest.main()
