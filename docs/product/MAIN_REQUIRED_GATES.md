# Main branch required gate matrix

## Current protection

Repository ruleset `Protect main` (ruleset ID `20842512`) is active on the default branch with:

- deletion protection;
- non-fast-forward protection;
- squash-only pull-request merges;
- required review-thread resolution;
- strict/up-to-date required status checks;
- required linear history;
- no bypass actors.

Current ruleset readback still requires only:

- `Backend tests`
- `PostgreSQL migration chain`
- `Frontend typecheck and build`
- `Docker Compose validation`

That matrix is narrower than the repository's current production-quality validation surface. This document records the intended target matrix; it does not itself change GitHub enforcement.

## Workflow behavior relevant to protection

The critical workflows now emit stable contexts suitable for branch protection:

- `Backend tests` is the Full Backend Pre-Merge aggregate. Full Backend is intentionally deferred until a PR is non-Draft / Ready for Review, and the 64-shard matrix is allocated only when the exact-head diff is backend-relevant.
- Continuous Integration runs on every PR to `main`, classifies dependency-lock and browser-E2E relevance internally, and emits stable aggregate context `Scoped CI gate` with `if: always()`.
- PostgreSQL concurrency runs on every PR to `main`, classifies relevance internally, and emits stable aggregate context `PostgreSQL concurrency gate` with `if: always()`.
- Operational Performance runs on every PR to `main`, classifies relevance internally, and emits stable aggregate context `Operational performance gate` with `if: always()`.
- Supply Chain Security runs on every PR to `main` and emits stable security contexts.
- Production Deployment Policy runs on every PR to `main` and emits stable context `Production environment policy`.

## Target required status checks

### Core CI

- `Backend tests`
- `PostgreSQL migration chain`
- `Frontend typecheck and build`
- `Docker Compose validation`
- `Scoped CI gate`

`Scoped CI gate` is the required aggregate for `Dependency lock consistency` and `Design partner browser E2E`. When either implementation job is selected for the exact diff, the aggregate fails unless that selected job succeeds. When an implementation job is not relevant, the aggregate accepts only its expected `skipped` or `success` result.

### PostgreSQL safety

- `PostgreSQL concurrency gate`

Require the aggregate gate, not dynamic matrix job names. Narrow PRs intentionally select only affected PostgreSQL groups; shared/runtime/workflow/ambiguous backend changes fail closed to the full selected safety surface.

### Supply-chain security

- `Production dependency audit and SBOM`
- `Secret history scan`
- `Container image vulnerability scan`

### Deployment policy

- `Production environment policy`

### Operational performance

- `Operational performance gate`

Require the aggregate gate, not the conditional `Live-stack performance smoke` implementation job.

## Contexts that must not be required globally

Do not require the conditional `Dependency lock consistency` or `Design partner browser E2E` implementation jobs directly when `Scoped CI gate` provides the stable always-emitted fail-closed aggregate.

Do not require dynamic PostgreSQL matrix job names such as individual scheduling, observation, review, authorization or admission-execution groups.

Do not require phase-specific/path-scoped contexts such as `SFTP N+1 recurring baseline transition`; unrelated PRs intentionally do not emit those checks.

Do not require a conditional implementation job when a stable aggregate gate exists.

## Safe activation sequence

1. Confirm every target stable context exists on the default branch and on a fresh pull request.
2. Ensure the current default-branch dependency baseline is clean under the intended Supply Chain checks before making those contexts required.
3. Update `Protect main` through an authorized GitHub administration surface.
4. Preserve strict/up-to-date checks, squash-only merging, review-thread resolution, linear history, deletion/non-fast-forward protection, and an empty bypass actor set.
5. Read the active ruleset back and verify the exact context matrix above.
6. Create a temporary proof PR in which one required critical check deliberately fails.
7. Confirm repository protection marks the PR non-mergeable without bypass.
8. Restore the check on the same proof branch and confirm mergeability returns after all required checks pass.
9. Close the proof PR without merging unless it contains an independently desired repository change.

## Important failure modes

Never require a context that is not guaranteed to be emitted for every PR targeting protected `main`. A missing required context can leave all PRs permanently waiting for a check that can never be reported.

Never activate a newly required fail-closed security context while the default branch itself contains a known failing baseline for that context. First land the reviewed baseline repair, then prove an unrelated fresh PR succeeds against the repaired default branch.

## Governance rule for new workflows

Any workflow that protects one of the following must be explicitly evaluated for required-gate treatment:

- financial authority or concurrency;
- authentication or MFA;
- tenant isolation;
- evidence integrity or processing leases;
- Production AI authorization;
- supply-chain security;
- deployment policy;
- operational performance;
- disaster recovery or data-loss prevention.

If a specialized workflow should not become a separate global required context, its critical result must be aggregated into an already-required stable gate or into a new stable always-emitted aggregate gate.

## Enforcement status

The expanded matrix is not yet proven active. Do not declare repository governance complete until:

- ruleset readback contains the exact target contexts;
- bypass actors remain empty;
- strict required-status-check policy remains enabled;
- the default-branch dependency baseline is clean under required Supply Chain checks;
- a deliberate failing required check blocks merge;
- restoring the check restores mergeability without bypass;
- this document still matches the actual workflow context names.
