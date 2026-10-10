# Branch protection required checks

This repository uses the active `Protect main` ruleset for protected-main merges.

## Required context design

Required contexts must be stable across pull requests. Optional or path-selected jobs are enforced through stable aggregate gates instead of being required directly.

### Core build and migration checks

- `Backend tests`
- `PostgreSQL migration chain`
- `Frontend typecheck and build`
- `Docker Compose validation`

### Stable aggregate gates

- `Scoped CI gate`
  - fails if general CI scope classification fails;
  - requires `Dependency lock consistency` when dependency validation is selected;
  - requires `Design partner browser E2E` when browser E2E is selected;
  - accepts intentional skips only when the successful classifier marked that scope not required.

- `PostgreSQL concurrency gate`
  - emitted on every pull request targeting `main`;
  - runs the selected PostgreSQL matrix group union for relevant diffs;
  - fails closed to all groups for shared/runtime/workflow/ambiguous backend changes;
  - succeeds cheaply for non-PostgreSQL-relevant diffs without starting PostgreSQL services;
  - fails if classification fails or any selected matrix validation fails/cancels.

- `Operational performance gate`
  - emitted on every pull request targeting `main`;
  - requires `Live-stack performance smoke` only for relevant API/web/scripts/Compose/performance-workflow changes;
  - succeeds cheaply for irrelevant diffs;
  - fails if scope classification fails.

### Security and production-policy checks

These workflows already run on every pull request to `main` and can be required directly:

- `Production dependency audit and SBOM`
- `Secret history scan`
- `Container image vulnerability scan`
- `Production environment policy`

## Contexts that should not be required directly

Do not require dynamic PostgreSQL matrix names such as `PostgreSQL concurrency (review)` or `PostgreSQL concurrency (scheduling)`. Narrow pull requests intentionally omit unrelated groups.

Do not rely on optional job contexts such as `Dependency lock consistency`, `Design partner browser E2E`, or `Live-stack performance smoke` as the sole protection boundary. Their stable aggregate gates are the protection contract.

## Target Protect main matrix

After the workflow changes are merged and exact check names are verified on a fresh pull request, the ruleset should require:

1. `Backend tests`
2. `PostgreSQL migration chain`
3. `Frontend typecheck and build`
4. `Docker Compose validation`
5. `Scoped CI gate`
6. `PostgreSQL concurrency gate`
7. `Operational performance gate`
8. `Production dependency audit and SBOM`
9. `Secret history scan`
10. `Container image vulnerability scan`
11. `Production environment policy`

Keep strict/up-to-date checks enabled, squash-only merging, linear history, unresolved-thread blocking, deletion/non-fast-forward protection, and an empty bypass list.

## Activation sequence

1. Merge the workflow changes with normal exact-head validation and fresh merge authorization.
2. Open a fresh narrow or docs-only proof pull request and verify all three stable aggregate gates are emitted.
3. Verify irrelevant PostgreSQL and performance work is skipped cheaply while their aggregate gates succeed.
4. Apply the target required-context matrix through an authorized GitHub administration surface.
5. Read back the active ruleset and verify the exact context set.
6. Prove enforcement with a deliberately failing critical gate on a temporary proof pull request.
7. Restore the check and verify mergeability returns without bypass.
8. Close Issue #461 only after repository readback proves enforcement is active.

The current GitHub connector used for repository work does not expose ruleset administration writes, so workflow preparation and evidence can be completed here, but the final ruleset mutation must be performed through an authorized GitHub admin surface.

## Read-only, independently reviewable Protect main API observation

A local, standard-library helper can read the currently active repository ruleset **without modifying GitHub permissions or protection**. It produces a new exclusive JSON snapshot; failures, missing required contexts, extra contexts, policy drift, or API errors are **NO-GO**. The committed synthetic unit tests exercise full protection, today's four-context failure, tampering, malformed API data and secret-safe error output.

```bash
# Run only in a controlled operator workspace, with optional read-scoped token.
python scripts/pilot_ruleset_evidence.py \
  --repo eh3aneba/maritime-claims-platform \
  --output /secure/pilot-releases/rc-001-ruleset-readback.json
```

The checker expects precisely the 11 stable target contexts above and also checks active enforcement, default-branch scoping, strict/up-to-date status checks, squash-only merges, resolved review threads, linear history, deletion and non-fast-forward protection, and zero bypass actors. It intentionally does **not** infer a PASS from successful PR workflow runs. It records no raw server payload, credentials, unexpected context names or exception text. Do not publish the generated record with sensitive operator notes.

**Critical remaining proof:** even a `metadata_complete: true` snapshot is *not* evidence that a deliberately failing critical check prevents merge. Perform the separate disposable failing-check experiment through authorized GitHub surfaces, preserve the exact PR/run/context IDs, restore the check without bypass, and independently verify the result. The tool always records `failing_check_enforcement_proven: false` and `pilot_authorized: false` until a separate human-approved evidence record establishes those facts. The repository connector cannot make the required administrative ruleset update. This step is an external admin action; the current four-context ruleset must be regarded as **NO-GO**.
