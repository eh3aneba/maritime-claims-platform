"""Offline bounded branch ruleset red->green observation: never claim Pilot GO."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ruleset_negative_enforcement as evidence  # noqa: E402

RED_SHA = "a" * 40
GREEN_SHA = "b" * 40
BASE_SHA = "c" * 40
TARGET = "Operational performance gate"


def fixtures(*, phase="red", sha=RED_SHA):
    policy = {
        "id": evidence.RULESET_ID,
        "name": "Protect main",
        "source": evidence.REPO,
        "source_type": "Repository",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        },
        "bypass_actors": [],
        "updated_at": "2026-10-12T12:00:00Z",
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
            {"type": "pull_request", "parameters": {
                "required_approving_review_count": 0,
                "allowed_merge_methods": ["squash"],
                "required_review_thread_resolution": True,
                "require_extra_approval_for_unattributed_changes": True,
            }},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
                "required_status_checks": [
                    {"context": n} for n in sorted(evidence.EXPECTED_CONTEXTS)
                ],
            }},
        ],
    }
    listed = [{
        "id": evidence.RULESET_ID,
        "name": "Protect main",
        "source": evidence.REPO,
        "source_type": "Repository",
    }]
    pr = {
        "number": 999,
        "state": "open",
        "draft": False,
        "mergeable": True,
        "mergeable_state": "blocked" if phase == "red" else "clean",
        "base": {"ref": "main", "sha": BASE_SHA,
                 "repo": {"full_name": evidence.REPO}},
        "head": {"ref": "pilot/synthetic-red-green", "sha": sha,
                 "repo": {"full_name": evidence.REPO}},
    }
    runs = [{
        "name": name,
        "id": index + (100 if phase == "green" else 1),
        "head_sha": sha,
        "app": {"slug": "github-actions"},
        "status": "completed",
        "conclusion": (
            "failure" if phase == "red" and name == TARGET else "success"
        ),
    } for index, name in enumerate(sorted(evidence.EXPECTED_CONTEXTS))]
    return listed, policy, pr, runs


def observed(*, phase="red", sha=RED_SHA):
    listed, policy, pr, runs = fixtures(phase=phase, sha=sha)
    return evidence.evaluate(
        listed=listed, ruleset=policy, pr=pr, runs=runs,
        pr_number=999, sha=sha, target=TARGET, phase=phase,
    )


class BranchProtectionNegativeReadbackTests(unittest.TestCase):
    def test_red_blocked_metadata_still_never_claims_actual_merge_refusal(self):
        r = observed()
        self.assertTrue(r["red_required_check_and_blocked_metadata_observed"])
        self.assertFalse(r["green_required_checks_and_clean_metadata_observed"])
        self.assertFalse(r["github_merge_api_refusal_actually_observed"])
        self.assertFalse(r["enforcement_causality_independently_verified"])
        self.assertFalse(r["pilot_authorized"])

    def test_green_clean_metadata_is_new_sha_not_permission(self):
        r = observed(phase="green", sha=GREEN_SHA)
        self.assertTrue(r["green_required_checks_and_clean_metadata_observed"])
        self.assertFalse(r["red_required_check_and_blocked_metadata_observed"])
        self.assertFalse(r["enforcement_causality_independently_verified"])
        self.assertFalse(r["pilot_authorized"])

    def test_rejects_unsafe_or_unactivated_ruleset(self):
        for operation in (
            lambda x: x["rules"][-1]["parameters"][
                "required_status_checks"
            ].pop(),
            lambda x: x["rules"][-1]["parameters"].update(
                strict_required_status_checks_policy=False),
            lambda x: x.update(bypass_actors=[{"actor_id": 1}]),
        ):
            listed, policy, pr, runs = fixtures()
            operation(policy)
            with self.assertRaises(evidence.NegativeObservationError):
                evidence.evaluate(
                    listed=listed, ruleset=policy, pr=pr, runs=runs,
                    pr_number=999, sha=RED_SHA, target=TARGET, phase="red",
                )

    def test_refuses_unrelated_failure_and_wrong_target_conclusion(self):
        for operation in (
            lambda a: a[0].update(conclusion="failure"),
            lambda a: next(x for x in a if x["name"] == TARGET).update(
                conclusion="skipped"),
            lambda a: a.append({"name": "Another optional workflow",
                                "conclusion": "failure"}),
        ):
            listed, policy, pr, runs = fixtures()
            operation(runs)
            with self.assertRaises(evidence.NegativeObservationError):
                evidence.evaluate(
                    listed=listed, ruleset=policy, pr=pr, runs=runs,
                    pr_number=999, sha=RED_SHA, target=TARGET, phase="red",
                )

    def test_refuses_unmergeable_conflict_draft_or_not_blocked(self):
        for field, value in (
            ("mergeable_state", "clean"),
            ("mergeable", False),
            ("draft", True),
            ("state", "closed"),
        ):
            listed, policy, pr, runs = fixtures()
            pr[field] = value
            with self.assertRaises(evidence.NegativeObservationError):
                evidence.evaluate(
                    listed=listed, ruleset=policy, pr=pr, runs=runs,
                    pr_number=999, sha=RED_SHA, target=TARGET, phase="red",
                )

    def test_only_newly_required_check_may_be_target(self):
        listed, policy, pr, runs = fixtures()
        with self.assertRaises(evidence.NegativeObservationError):
            evidence.evaluate(
                listed=listed, ruleset=policy, pr=pr, runs=runs,
                pr_number=999, sha=RED_SHA, target="Backend tests", phase="red",
            )

    def test_matching_pair_stays_unverified_without_human_review(self):
        red = observed()
        green = observed(phase="green", sha=GREEN_SHA)
        red["observed_at_utc"] = "2026-10-12T10:00:00Z"
        green["observed_at_utc"] = "2026-10-12T10:05:00Z"
        result = evidence.compare(red, green)
        self.assertTrue(result["red_blocked_and_green_clean_metadata_pair"])
        self.assertFalse(result["actual_required_check_merge_refusal_independently_verified"])
        self.assertTrue(result["independent_operator_review_still_required"])
        self.assertFalse(result["pilot_authorized"])

    def test_pair_must_be_same_pr_target_baseline_and_newer_sha(self):
        for key, value in (
            ("pr_number", 1000),
            ("target_required_check", "Secret history scan"),
            ("pr_base_sha", "d" * 40),
            ("pr_head_ref", "pilot/other-branch"),
            ("ruleset_updated_at", "2026-10-12T10:10:00Z"),
            ("pr_head_sha", RED_SHA),
            ("target_check_run_id", 1),
            ("observed_at_utc", "2026-10-12T09:00:00Z"),
        ):
            red = observed()
            green = observed(phase="green", sha=GREEN_SHA)
            red["observed_at_utc"] = "2026-10-12T10:00:00Z"
            green["observed_at_utc"] = "2026-10-12T10:05:00Z"
            green[key] = value
            with self.assertRaises(evidence.NegativeObservationError):
                evidence.compare(red, green)

    def test_pair_cannot_convert_fake_metadata_to_go(self):
        red = observed()
        green = observed(phase="green", sha=GREEN_SHA)
        red["observed_at_utc"] = "2026-10-12T10:00:00Z"
        green["observed_at_utc"] = "2026-10-12T10:05:00Z"
        for key, value in (
            ("pilot_authorized", True),
            ("enforcement_causality_independently_verified", True),
            ("github_merge_api_refusal_actually_observed", True),
            ("eleven_required_contexts_observed", False),
        ):
            tampered = deepcopy(green)
            tampered[key] = value
            with self.assertRaises(evidence.NegativeObservationError):
                evidence.compare(red, tampered)


if __name__ == "__main__":
    unittest.main()
