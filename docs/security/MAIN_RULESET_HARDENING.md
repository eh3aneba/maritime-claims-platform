# Main ruleset hardening

Tracking issue: #461

## Purpose

The active `Protect main` repository ruleset must fail closed on the repository's
critical production checks. Workflow presence alone is not enough: a check that
is not listed in the required-status-check rule can fail while GitHub still
allows the pull request to be merged.

This document records the exact stable check contexts to require, why the
aggregate contexts are used, and how to prove the resulting protection.

## Current readback

Ruleset:

- name: `Protect main`
- ID: `20842512`
- target: default branch
- enforcement: active
- strict / up-to-date status checks: enabled
- pull requests required
- unresolved review threads must be resolved
- allowed merge method: squash only
- linear history required
- bypass actors: none

At the time of the Phase 17.6-AE closure, the required-status-check rule still
contains only:

1. `Backend tests`
2. `PostgreSQL migration chain`
3. `Frontend typecheck and build`
4. `Docker Compose validation`

That is insufficient because the production security, concurrency, E2E scope,
performance and deployment-policy gates are not enforced by the ruleset.

## Required context matrix

Keep the four existing contexts and require all of the following stable
contexts:

1. `Backend tests`
2. `PostgreSQL migration chain`
3. `Frontend typecheck and build`
4. `Docker Compose validation`
5. `Scoped CI gate`
6. `PostgreSQL concurrency gate`
7. `Operational performance gate`
8. `Production environment policy`
9. `Production dependency audit and SBOM`
10. `Secret history scan`
11. `Container image vulnerability scan`

Use the job/check context names above, not the workflow display names.

### Why aggregate contexts are required

`Scoped CI gate` is the invariant result for path-selected
`Dependency lock consistency` and `Design partner browser E2E`. It succeeds
only when skipped work was legitimately not required, and fails when selected
work fails or is unexpectedly skipped.

`PostgreSQL concurrency gate` performs the same invariant enforcement for the
path-selected PostgreSQL concurrency matrix.

`Operational performance gate` performs the same invariant enforcement for
the path-selected live-stack performance smoke.

`Backend tests` is the stable aggregate for Full Backend Pre-Merge. On a
non-backend change it emits a successful classified no-work result; on a
backend-relevant change it requires the full backend shard matrix to succeed.

Do not require individual dynamic PostgreSQL matrix job names or individual
backend shard names.

Do not separately require `Design partner browser E2E` or
`Dependency lock consistency` when `Scoped CI gate` is required. Those jobs
are intentionally path-selected; the aggregate is the stable fail-closed
contract.

## Administrative change

The ruleset change requires repository administration authority.

In GitHub repository settings:

1. Open **Settings → Rules → Rulesets**.
2. Open **Protect main**.
3. Edit the required status checks rule.
4. Preserve the existing four contexts.
5. Add the seven missing stable contexts from the matrix above.
6. Preserve strict/up-to-date checks.
7. Preserve squash-only merge, linear history and unresolved-thread blocking.
8. Keep bypass actors empty.
9. Save the ruleset.

Do not change enforcement to evaluate/disabled during this operation.

## Readback verification

After saving, fetch the active ruleset and confirm the
`required_status_checks` set is exactly the intended matrix (additional
purposefully approved contexts are acceptable, missing contexts are not).

Example read-only verification:

```bash
curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/eh3aneba/maritime-claims-platform/rulesets/20842512 \
  | jq -r '
      .rules[]
      | select(.type == "required_status_checks")
      | .parameters.required_status_checks[]
      | .context
    ' \
  | sort
```

Expected contexts:

```text
Backend tests
Container image vulnerability scan
Docker Compose validation
Frontend typecheck and build
Operational performance gate
PostgreSQL concurrency gate
PostgreSQL migration chain
Production dependency audit and SBOM
Production environment policy
Scoped CI gate
Secret history scan
```

Also confirm:

- `enforcement == "active"`;
- the pull-request rule still requires review-thread resolution;
- allowed merge methods remain `squash` only;
- linear-history rule remains present;
- `bypass_actors` remains empty.

## Deliberate fail-closed proof

Do this only after the ruleset readback is correct.

Use a disposable branch and pull request. Do not merge it.

1. Branch from current `main`.
2. Make one temporary branch-only edit to
   `.github/workflows/production-deployment-policy.yml` that causes the
   `Production environment policy` job to exit non-zero.
3. Open a non-draft PR against `main`.
4. Confirm `Production environment policy` fails.
5. Confirm GitHub reports the PR as blocked from merge because a required check
   is failing. Do not use an admin bypass.
6. Revert the temporary failing edit on the same branch.
7. Confirm the policy context turns green on the new exact head.
8. Confirm mergeability returns without bypass.
9. Close the proof PR unmerged and delete the disposable branch.

The proof must not alter production configuration, application code, secrets or
the default branch.

## Evidence to attach to #461

Record:

- ruleset readback after the administrative change;
- exact required-context list;
- proof PR number;
- failing exact-head SHA and failed required context;
- evidence that merge was blocked;
- restored exact-head SHA and successful required context;
- evidence that mergeability returned without bypass.

Only then may #461 be closed.

## Connector boundary

The managed GitHub connector used during the Phase 17.6-AE work exposes
ruleset readback but not repository-administration mutation. Repository code,
workflow definitions, documentation and verification evidence can be prepared
through that connector, but it must not claim that protection is active until
the administrative ruleset write and readback proof have actually occurred.
