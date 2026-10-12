#!/usr/bin/env python3
"""Local GitHub Admin-only, fail-closed activation of 11 Protect main checks.

Default mode is read-only. Only --apply plus an explicit approval ticket and
ruleset ID permit one PUT to the *existing* ruleset, never a new ruleset.
Do not run on a customer environment or put an admin token in source control.
A ruleset readback is NOT a failing-required-check merge-block experiment.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pilot_ruleset_evidence import (
    EXPECTED_CONTEXTS, EvidenceError, evaluate as evaluate_ruleset,
    fetch as fetch_ruleset,
)
from pilot_required_check_preflight import (
    GatePreflightError, evaluate as evaluate_checks, fetch as fetch_checks,
)

REPO = "eh3aneba/maritime-claims-platform"
RULESET_ID = 20842512
ORIGINAL = frozenset({
    "Backend tests", "PostgreSQL migration chain",
    "Frontend typecheck and build", "Docker Compose validation",
})
TICKET = re.compile(r"ticket://[A-Za-z0-9][A-Za-z0-9._/-]{3,99}\Z")


class ActivationError(ValueError):
    """Sanitized error: no API response, hostnames, tokens or secrets."""


def make_proposal(listed: object, detail: object, check_record: object) -> dict:
    if (not isinstance(check_record, dict)
            or check_record.get("all_required_checks_green") is not True
            or check_record.get("exact_name_contexts_present") != len(EXPECTED_CONTEXTS)
            or not isinstance(check_record.get("expected_checks"), dict)
            or set(check_record["expected_checks"]) != EXPECTED_CONTEXTS
            or any(x.get("outcome") != "pass" for x in check_record["expected_checks"].values())
            or check_record.get("repository") != REPO):
        raise ActivationError("current open PR check-name preflight incomplete")
    try:
        state = evaluate_ruleset(listed, detail, repo=REPO)
    except EvidenceError:
        raise ActivationError("live Protect main ruleset readback invalid") from None
    if (state["ruleset_id"] != RULESET_ID
            or state["unexpected_context_count"] != 0
            or not all(state["safety_properties"].values())):
        raise ActivationError("Protect main identity or security invariants changed")
    if not isinstance(detail, dict) or len(detail.get("rules", [])) < 1:
        raise ActivationError("Protect main rules are malformed")
    rules = detail["rules"]
    checked = [x for x in rules if x.get("type") == "required_status_checks"]
    if len(checked) != 1:
        raise ActivationError("required status-check rule ambiguous")
    existing = checked[0]["parameters"]["required_status_checks"]
    current = [x["context"] for x in existing]
    if len(current) != len(set(current)):
        raise ActivationError("duplicate required context in live ruleset")
    if set(current) != ORIGINAL:
        raise ActivationError("expected exact four-context starting state missing")
    missing = EXPECTED_CONTEXTS - ORIGINAL
    if set(state["missing_expected_contexts"]) != missing or len(missing) != 7:
        raise ActivationError("requested seven-context change is not exact")
    result = {
        "name": detail["name"],
        "target": detail["target"],
        "enforcement": detail["enforcement"],
        "bypass_actors": deepcopy(detail["bypass_actors"]),
        "conditions": deepcopy(detail["conditions"]),
        "rules": deepcopy(rules),
    }
    updated = next(r for r in result["rules"] if r["type"] == "required_status_checks")
    updated["parameters"]["required_status_checks"] = (
        deepcopy(existing) + [{"context": name} for name in sorted(missing)]
    )
    if (len(updated["parameters"]["required_status_checks"]) != 11
            or set(x["context"] for x in updated["parameters"]["required_status_checks"])
            != EXPECTED_CONTEXTS):
        raise ActivationError("generated ruleset would not require exactly eleven contexts")
    return result


def _fingerprint(detail: object) -> str:
    if not isinstance(detail, dict):
        raise ActivationError("ruleset state not available")
    # Compare the full server-returned metadata to detect intervening changes
    # before PUT. This is *not* an atomic GitHub compare-and-swap.
    return json.dumps(detail, sort_keys=True, separators=(",", ":"))


def _write_ruleset(data: dict, token: str) -> None:
    if not token:
        raise ActivationError("GitHub Admin token unavailable")
    endpoint = f"https://api.github.com/repos/{REPO}/rulesets/{RULESET_ID}"
    req = Request(
        endpoint,
        data=json.dumps(data, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "mcri-pilot-protect-main-admin-v1",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        with urlopen(req, timeout=25) as response:
            if response.status != 200:
                raise ActivationError("GitHub did not accept the ruleset update")
            # Never echo the response body or server errors; GET again separately.
            if len(response.read(1024 * 1024 + 1)) > 1024 * 1024:
                raise ActivationError("GitHub returned oversized ruleset response")
    except (HTTPError, URLError, TimeoutError, OSError):
        raise ActivationError("GitHub Admin ruleset update failed or outcome uncertain") from None


def execute(*, pr: int, sha: str, apply: bool, ticket: str | None,
            confirmed_id: int | None, token: str | None) -> dict:
    if type(pr) is not int or pr <= 0:
        raise ActivationError("positive current-open PR number required")
    if apply and (confirmed_id != RULESET_ID or not ticket or not TICKET.fullmatch(ticket)):
        raise ActivationError("explicit ruleset ID and approved change ticket required")
    try:
        open_pr, runs = fetch_checks(repo=REPO, pr_number=pr, sha=sha, token=token)
        check_record = evaluate_checks(
            open_pr, runs, repo=REPO, pr_number=pr, exact_sha=sha,
        )
        listed, detail = fetch_ruleset(repo=REPO, token=token)
    except (GatePreflightError, EvidenceError):
        raise ActivationError("exact-head preflight or ruleset readback unavailable") from None
    proposal = make_proposal(listed, detail, check_record)
    changed = False
    required = 4
    if apply:
        # Refresh immediately before mutation to minimize stale-configuration
        # risk. GitHub's PUT does not guarantee atomic compare-and-swap.
        try:
            fresh_list, fresh_detail = fetch_ruleset(repo=REPO, token=token)
        except EvidenceError:
            raise ActivationError("pre-update ruleset recheck unavailable") from None
        if (_fingerprint(fresh_detail) != _fingerprint(detail)
                or make_proposal(fresh_list, fresh_detail, check_record) != proposal):
            raise ActivationError("ruleset drifted before proposed update")
        # Also recheck that the exact proof PR remains open and on the
        # identical head after the Admin approval/review window.
        try:
            fresh_pr, fresh_runs = fetch_checks(
                repo=REPO, pr_number=pr, sha=sha, token=token,
            )
            fresh_record = evaluate_checks(
                fresh_pr, fresh_runs, repo=REPO, pr_number=pr,
                exact_sha=sha,
            )
        except GatePreflightError:
            raise ActivationError("open proof PR changed before update") from None
        if (not fresh_record["all_required_checks_green"]
                or fresh_record["expected_checks"] != check_record["expected_checks"]):
            raise ActivationError("proof check identities changed before update")
        _write_ruleset(proposal, token or "")
        changed = True
        # Successful PUT by itself is not 11/11 proof: read back separately.
        try:
            observed_list, observed_detail = fetch_ruleset(repo=REPO, token=token)
            after = evaluate_ruleset(observed_list, observed_detail, repo=REPO)
        except EvidenceError:
            raise ActivationError("ruleset update sent; independent readback unavailable") from None
        if after["ruleset_id"] != RULESET_ID or not after["metadata_complete"]:
            raise ActivationError("ruleset update sent; 11/11 security readback NOT confirmed")
        required = after["required_context_count"]
    return {
        "schema": "mcri-pilot-main-ruleset-admin-handoff-v1",
        "repository": REPO,
        "ruleset_id": RULESET_ID,
        "pr_number": pr,
        "exact_open_pr_head_sha": sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "current_required_checks": required,
        "intended_required_checks": len(EXPECTED_CONTEXTS),
        "exact_open_pr_check_emission_verified": True,
        "ruleset_update_sent": changed,
        "eleven_check_ruleset_readback_confirmed": changed and required == 11,
        "deliberate_failed_required_check_merge_refusal_proven": False,
        "customer_pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ticket", help="private approved ticket:// reference")
    parser.add_argument("--confirm-ruleset-id", type=int)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        print("NO-GO: result would overwrite an existing record", file=sys.stderr)
        return 2
    try:
        result = execute(
            pr=args.pr, sha=args.sha, apply=args.apply,
            ticket=args.ticket, confirmed_id=args.confirm_ruleset_id,
            token=os.environ.get("GITHUB_TOKEN"),
        )
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except ActivationError:
        print("NO-GO: admin preflight/update not independently complete", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: exclusive operator result unavailable", file=sys.stderr)
        return 2
    if not args.apply:
        print("DRY RUN ONLY: exact 4->11 proposal prepared, no GitHub setting changed.")
    else:
        print("RULESET 11/11 LIVE READBACK CONFIRMED; negative merge test still required.")
    print("No real-data Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
