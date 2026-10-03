# Repository protection required-gate matrix

This document records the intended required status-check matrix for the repository's active `Protect main` ruleset.

It is an operational specification, not proof that GitHub enforcement is currently configured. The active ruleset must be read back after any administration change before enforcement is considered complete.

## Current policy

The default branch must remain protected by:

- pull-request-only integration;
- strict/up-to-date required checks;
- squash-only merging;
- linear history;
- unresolved review-thread blocking;
- deletion and non-fast-forward protection;
- no bypass actors.

Full Backend validation is intentionally deferred until a PR is non-Draft / Ready for Review. The stable required context is `Backend tests`; its workflow classifies whether the 64-shard backend matrix is required for the exact head.

## Required status checks

The intended stable matrix is:

### Core CI

- `Backend tests`
- `PostgreSQL migration chain`
- `Frontend typecheck and build`
- `Docker Compose validation`
- `Dependency lock consistency`
- `Design partner browser E2E`

### PostgreSQL safety

- `PostgreSQL concurrency gate`

The aggregate gate must be required instead of individual matrix-group job names. The PostgreSQL workflow runs on every PR to `main`, classifies relevance internally, and emits this stable aggregate context with `if: always()`.

### Supply-chain security

- `Production dependency audit and SBOM`
- `Secret history scan`
- `Container image vulnerability scan`

These checks are stable PR contexts. Image scanning may classify an exact diff as not affecting production image build contexts, but the check context must still be emitted.

### Deployment policy

- `Production environment policy`

### Operational performance

- `Operational performance gate`

The aggregate performance gate must be required instead of relying on the conditional `Live-stack performance smoke` job. The workflow runs on every PR to `main`, classifies relevance internally, and emits the stable aggregate context with `if: always()`.

## Contexts that must not be required directly

Do not require dynamic PostgreSQL matrix job names. Narrow PRs intentionally select only affected groups.

Do not require phase-specific/path-scoped checks such as `SFTP N+1 recurring baseline transition` as a global branch-protection context. Such a context is intentionally absent on unrelated PRs and would make those PRs permanently unmergeable if required globally.

Do not require a conditional implementation job when a stable aggregate gate exists; require the aggregate instead.

## Safe administration sequence

1. Confirm every intended stable context exists on the default branch and on a fresh PR.
2. Update the active `Protect main` ruleset through an authorized GitHub administration surface.
3. Preserve strict/up-to-date checks, squash-only merge, linear history, unresolved-thread blocking, deletion/non-fast-forward protection, and an empty bypass list.
4. Read the active ruleset back and verify the exact context matrix above.
5. Create a deliberate proof PR in which one required critical check fails.
6. Verify GitHub reports the PR as non-mergeable without bypass.
7. Restore the check on the same proof branch and verify mergeability returns after all required checks pass.
8. Close the proof PR without merging unless it contains an independently desired repository change.

## Evidence required before governance closure

Repository governance must not be declared complete until all of the following are true:

- active ruleset readback contains the complete required matrix;
- bypass actors are empty;
- strict required-status-check policy remains enabled;
- a deliberately failing required check blocks merge;
- restoring the check restores mergeability without bypass;
- this document still matches the actual workflow context names.

## Change-control rule

When a critical workflow is renamed, replaced, made conditional, or split, branch-protection context compatibility must be evaluated before merge. Never remove or rename a required context in a way that can leave `main` either unprotected or permanently unmergeable.
