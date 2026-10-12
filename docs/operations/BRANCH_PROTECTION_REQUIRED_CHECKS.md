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

Keep strict/up-to-date checks enabled, **enforce required checks on creation** (`do_not_enforce_on_create=false`), **require extra approval for unattributed changes** (`require_extra_approval_for_unattributed_changes=true`), squash-only merging, linear history, unresolved-thread blocking, deletion/non-fast-forward protection, and an empty bypass list.

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

The checker expects precisely the 11 stable target contexts above and also checks active enforcement, default-branch scoping, strict/up-to-date status checks, enforcement on creation, extra approval for unattributed changes, squash-only merges, resolved review threads, linear history, deletion and non-fast-forward protection, and zero bypass actors. It intentionally does **not** infer a PASS from successful PR workflow runs. It records no raw server payload, credentials, unexpected context names or exception text. Do not publish the generated record with sensitive operator notes.

**Critical remaining proof:** even a `metadata_complete: true` snapshot is *not* evidence that a deliberately failing critical check prevents merge. Perform the separate disposable failing-check experiment through authorized GitHub surfaces, preserve the exact PR/run/context IDs, restore the check without bypass, and independently verify the result. The tool always records `failing_check_enforcement_proven: false` and `pilot_authorized: false` until a separate human-approved evidence record establishes those facts. The repository connector cannot make the required administrative ruleset update. This step is an external admin action; the current four-context ruleset must be regarded as **NO-GO**.

## Read-only exact-PR-head context-emission preflight

Before a repository Admin updates `Protect main`, confirm that all **11**
required context names are actually emitted and successful on the **exact head**
of one current, open, same-repository PR targeting `main`. A successful
workflow-name row is not sufficient evidence that the stable job/context
existed: e.g. a green `PostgreSQL Concurrency Regression Suite` is *not* by
itself a `PostgreSQL concurrency gate` check run.

Use the standard-library read-only checker (requires only a read-scoped GitHub
token for private repositories; creates a local exclusive non-secret record):

```bash
python scripts/pilot_required_check_preflight.py \
  --repo eh3aneba/maritime-claims-platform \
  --pr "<reviewed-open-proof-PR-number>" \
  --sha "<independently-verified-PR-head-40-character-SHA>" \
  --output /secure/pilot-releases/check-contexts-before-admin-change.json
```

The program reads only `GET /pulls/{number}` and paginated
`GET /commits/{sha}/check-runs`; it verifies PR ownership/base, current exact
head SHA, `github-actions` application identity, **one unambiguous** check run
per expected stable name, and `completed/success` for all eleven. Missing,
in-progress, failed, skipped, renamed, duplicated, wrong-SHA or third-party
check identities cause **NO-GO**, rather than guessing what a ruleset can
require. Unknown unrelated check names are never copied into evidence.
The emitted record always includes
`ruleset_mutated=false`, `failing_required_check_enforcement_proven=false`
and `pilot_authorized=false`. If another commit lands on the proof PR,
discard the old readback and rerun with its new head.


## Controlled red→blocked→green proof snapshots after Admin activation

**Only after the repository Admin independently confirms 11/11 active
required contexts** and preserves all branch safety properties, open a
temporary **same-repository synthetic-only PR** to `main`. Do not use
production data and do not weaken the ruleset for the exercise.

1. Deliberately make **exactly one newly required stable aggregate
   context** fail on the disposable PR. Check that the other ten required
   contexts succeed, no other optional check fails, the PR has no merge
   conflicts and no draft/review issue. Choose a deterministic failure
   that remains isolated to the disposable synthetic test branch.
   Capture the exact *red* PR HEAD SHA from GitHub.
2. Let GitHub complete status propagation, then use the read-only
   observer. It requires live **11/11 active Ruleset** and exact
   GitHub Actions check-run names and identities. The target must
   actually be `completed/failure`; all other ten must be green;
   GitHub PR merge metadata must be `mergeable=true` and
   `mergeable_state=blocked`. This is metadata, **not a merge
   attempt or independent causal proof**:

```bash
python scripts/pilot_ruleset_negative_enforcement.py capture \
  --pr "<disposable-PR-number>" \
  --sha "<red-full-40-character-PR-head>" \
  --target-check "Operational performance gate" \
  --phase red \
  --output /secure/pilot-releases/required-red-blocked.json
```

3. Correct the **same** disposable PR so a **new SHA** has all 11
   checks green. Verify `mergeable_state=clean` and no unrelated
   security, operational or reviewer blockers. Collect the new green
   record:

```bash
python scripts/pilot_ruleset_negative_enforcement.py capture \
  --pr "<same-disposable-PR-number>" \
  --sha "<green-full-40-character-PR-head>" \
  --target-check "Operational performance gate" \
  --phase green \
  --output /secure/pilot-releases/required-green-clean.json
```

4. Compare the **two private exact-HEAD snapshots**; the checker
   requires the same PR, base SHA, HEAD branch and unchanged ruleset
   `updated_at`, the same failing-then-restored required context,
   two distinct check run IDs and SHA values, and ordered UTC captures.

```bash
python scripts/pilot_ruleset_negative_enforcement.py compare \
  --red /secure/pilot-releases/required-red-blocked.json \
  --green /secure/pilot-releases/required-green-clean.json \
  --output /secure/pilot-releases/required-check-contrast.json
```

This is **strictly read-only**: it never calls a GitHub merge endpoint,
creates a PR, modifies a ruleset, or changes a test. It is intentionally
conservative, and the outputs **always** say
`github_merge_api_refusal_actually_observed=false`,
`enforcement_causality_independently_verified=false`,
`actual_required_check_merge_refusal_independently_verified=false`
and `pilot_authorized=false` where applicable.

**Mandatory independent closeout**: a separately authorized operator
must confirm the red merge was unavailable *because the newly required
check failed*, not because of another restriction, preserve an approved
GitHub UI/API merge-block receipt (without forcing or attempting a
potentially valid merge), and then verify green eligibility returned
without bypass. Store the reviewer, approved change ticket, exact PR,
ruleset and context/run references privately. No actual failing-check
refusal has been independently observed until that operator exercise.
Only then may #461 be reviewed for closure. `metadata_complete`
alone is insufficient for Pilot GO.

### Admin-only changes (not executed by this repository tool)

1. Through authorized GitHub repository **Settings → Rules → Rulesets →
   Protect main**, review the active ruleset and its present four required
   check contexts. Do not create a duplicate or loosen bypass/review settings.
2. If the exact-PR preflight passed, add only these seven **stable** contexts
   to the existing four: `Scoped CI gate`,
   `PostgreSQL concurrency gate`, `Operational performance gate`,
   `Production dependency audit and SBOM`, `Secret history scan`,
   `Container image vulnerability scan` and `Production environment policy`.
   Choose each exact context supplied by GitHub's checks picker. Never add
   optional/path-selected matrix jobs in their place.
3. Preserve **strict/up-to-date required checks**, the required checks on
   branch creation, extra approval for unattributed changes, squash-only,
   linear history, resolved review threads, non-fast-forward/deletion
   protection, and **zero** bypass actors. Save through the Admin UI only
   with an approved change ticket.
4. Re-run `scripts/pilot_ruleset_evidence.py` against the live ruleset and
   require exact **11/11** readback. Store the new record with the approved
   change ticket. Do not treat a healthy PR as proof that the settings changed.
5. Use a disposable, **synthetic-only** PR to intentionally fail **one now
   required stable check** without touching customer data or weakening branch
   settings. Confirm through the UI/API that GitHub refuses protected-main
   merge. Repair the disposable test on that PR, confirm its exact-head
   check turns green and that merge eligibility returns **without a bypass**.
   Record PR/check run IDs, the before/after state and independent Admin
   approval in controlled operator storage; don't merge the intentionally
   broken test.
6. Mark #461 complete only after the verified live readback and negative
   enforcement experiment. The preflight checker **never** changes repository
   settings or performs the negative exercise, and a merely user-entered
   attestation does not establish the protection actually operated.

This is a gating dependency for #647/#653 and controlled Pilot v1. A
successful 11/11 check-run **emission** preflight is not a live 11/11
ruleset, and neither alone authorizes customer claims.
