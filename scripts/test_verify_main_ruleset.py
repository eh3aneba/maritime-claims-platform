#!/usr/bin/env python3
"""Unit tests for the read-only main ruleset verifier."""

from __future__ import annotations

import copy
import unittest

from verify_main_ruleset import REQUIRED_CONTEXTS, VerificationError, verify_ruleset


def compliant_ruleset() -> dict:
    return {
        "name": "Protect main",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "exclude": [],
                "include": ["~DEFAULT_BRANCH"],
            }
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_review_thread_resolution": True,
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["squash"],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": context}
                        for context in sorted(REQUIRED_CONTEXTS)
                    ],
                },
            },
            {"type": "required_linear_history"},
        ],
        "bypass_actors": [],
    }


class RulesetVerifierTests(unittest.TestCase):
    def test_compliant_ruleset_passes(self) -> None:
        contexts = verify_ruleset(compliant_ruleset())
        self.assertEqual(contexts, sorted(REQUIRED_CONTEXTS))

    def test_missing_required_context_fails(self) -> None:
        ruleset = compliant_ruleset()
        status_rule = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        status_rule["parameters"]["required_status_checks"] = [
            {"context": "Backend tests"}
        ]

        with self.assertRaisesRegex(VerificationError, "missing required contexts"):
            verify_ruleset(ruleset)

    def test_nonempty_bypass_fails(self) -> None:
        ruleset = compliant_ruleset()
        ruleset["bypass_actors"] = [{"actor_type": "OrganizationAdmin"}]

        with self.assertRaisesRegex(VerificationError, "bypass_actors"):
            verify_ruleset(ruleset)

    def test_missing_bypass_field_fails_closed(self) -> None:
        ruleset = compliant_ruleset()
        del ruleset["bypass_actors"]

        with self.assertRaisesRegex(VerificationError, "bypass_actors"):
            verify_ruleset(ruleset)

    def test_weakened_pull_request_policy_fails(self) -> None:
        ruleset = compliant_ruleset()
        pull_rule = next(
            rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
        )
        pull_rule["parameters"]["allowed_merge_methods"] = ["merge", "squash"]

        with self.assertRaisesRegex(VerificationError, "squash-only"):
            verify_ruleset(ruleset)

    def test_ref_exclusion_fails(self) -> None:
        ruleset = compliant_ruleset()
        ruleset["conditions"]["ref_name"]["exclude"] = ["refs/heads/emergency"]

        with self.assertRaisesRegex(VerificationError, "ref exclusions"):
            verify_ruleset(ruleset)

    def test_enforcement_on_create_must_remain_enabled(self) -> None:
        ruleset = compliant_ruleset()
        status_rule = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        status_rule["parameters"]["do_not_enforce_on_create"] = True

        with self.assertRaisesRegex(VerificationError, "branch creation"):
            verify_ruleset(ruleset)


if __name__ == "__main__":
    unittest.main()
