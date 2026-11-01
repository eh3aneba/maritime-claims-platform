# CI Acceleration v2: one backend collection per run

Status: Draft PR candidate for hosted review; no merge authorized. Source baseline:
`fa2c471463f5aecb988f89e791aae359385227e4`. No application, insurance-claim,
dependency, PostgreSQL concurrency, browser, performance, security, or branch
protection behavior is changed.

## Evidence and bottlenecks

Inspected `backend-premerge.yml`, `postgres-concurrency-regressions.yml`,
`ci.yml` (Continuous Integration), and `performance-smoke.yml` (Operational
Performance Smoke), their selectors, the required-check contract, and PostgreSQL
due-tick incident notes. The GitHub Actions runs API returned `Forbidden` from
this environment. Hosted queue times, current step timings, cache hit rates,
and the live ruleset were therefore not independently read back. Counts below
come from the checked-in workflows; timings are local measurements or explicitly
attributed historical repository evidence.

The hosted comparison baseline supplied by the maintainer is
[SeeClaims issue #553](https://github.com/eh3aneba/maritime-claims-platform/issues/553):
approximately **44 minutes median Full Backend wall time**, and approximately
**505 runner-minutes across the 64 backend shard jobs in PR #864**. These are the
actual hosted reference figures for this proposal. They were supplied in the
review request; the issue could not be independently fetched through the blocked
GitHub API. Do not replace these figures with the local collection-work model
below, or interpret the model's 97.6% component reduction as an end-to-end gain.

| Source | Evidence | Consequence |
| --- | --- | --- |
| Backend setup and collection | 64 jobs each install the same hash-locked dev dependencies, run `pip check`, compile, and call the selector, which runs `pytest --collect-only -q tests` over the entire suite | Repeats full collection 64 times. `setup-python` caches pip downloads, not installed environments. The per-job installs still run |
| Backend allocation and skew | Current collection has 1,591 nodes; SHA-256 assignment gives 13–39 nodes per shard, without duration weighting | Fixed 64-job fan-out costs runner setup/queue capacity and does not balance expensive fixture chains. Counts alone do not justify removing shards or tests |
| PostgreSQL setup | Full backend changes select 17 independently provisioned PostgreSQL groups, each installing dev dependencies and applying the complete migration chain | Together with 64 backend installs and general CI's production-dependency migration job, a full path has 82 backend dependency installs before browser/security/image work |
| PostgreSQL test latency | `POSTGRES_DUE_TICK_CI_TRIAGE.md` records five-test steps at 727.59s and 395.14s, and nested v1-admission fixtures at 104.839s and 98.881s | Repeated canonical lineage setup and intentional serialization are documented costs. These historical samples are not current-run measurements or proof of deadlock. Nested fixture times must not be added to parent durations |
| Overlapping stack setup | General CI browser E2E and Operational Performance each call `design_partner_preflight.sh`, building and booting a separate Docker/PostgreSQL/ClamAV/API/worker/web stack | Overlaps dependency/image/seed work. The performance workflow additionally validates security, backup, restart, and recovery on a fresh runner; those are distinct required validations |
| Other fixed work | General CI migration, frontend typecheck/build, and Compose checks run independently of the general scope classifier; four classifiers fetch full history | Potential fixed overhead on narrow changes. No current timing evidence quantifies its share |
| Existing scope savings | Backend already skips the product matrix for irrelevant diffs and narrowly admits only three audited synthetic test modules; PostgreSQL selects group unions; browser and performance have guarded scope selectors | Do not reintroduce broad path skips or claim these existing savings as v2 improvements |

Expensive single-test PostgreSQL groups may be overhead-heavy, but merging groups
could worsen the critical path because fixture costs differ substantially.
Likewise, 64 backend shards may be excessive for cheap nodes but necessary for
the slowest lineage tests. No shard allocation or coverage reduction is proposed
without hosted duration and queue evidence.

## Proposed change

Collect the full backend suite once in a new `Backend collection manifest` job,
only when the unchanged classifier selects full backend validation. It uses
the same Python 3.13, lockfile, and explicit environment as the shards.

The producer and all 64 shards explicitly check out `${{ github.sha }}`. On
`pull_request` this is GitHub's tested merge commit, not
`${{ github.event.pull_request.head.sha }}`; on manual dispatch it is the event's
commit. The selector verifies actual `HEAD^{commit}` equals the supplied event
SHA, obtains `HEAD^{tree}`, and rejects staged changes, tracked modifications,
or nonignored untracked files. Both identities are verified again after producer
collection, so collection cannot silently change the checkout being described.

The selector writes a JSON manifest containing schema version, verified checkout
commit and tree, shard count, node count, and all collected nodes. Collection
must succeed, and its reported total must equal the parsed node count; nodes must be
nonempty, unique, and valid; every one of the 64 hash buckets must be nonempty.
The producer exposes the SHA-256 of the exact manifest bytes through its job
output and uploads an immutable, one-day artifact.

Each existing shard downloads that artifact from its current workflow run,
checks its digest against the producer output, checks the actual commit and tree
against the manifest, checks shard and node counts, and emits the original
NUL-delimited node arguments. There is no cache,
cross-run lookup, fallback collection, or success on an empty selection. Missing,
stale, changed, truncated, invalid, or expired artifacts fail the job. The download
name comes from the producer's output, preserving its attempt identity when only
failed downstream jobs are rerun. If an artifact has expired, rerun all jobs.

The producer and consumers bind to the checkout's `GITHUB_SHA`, including the
normal PR merge commit; this does not silently switch validation to another ref.
The producer is a dependency of the matrix and the final `Backend tests` gate.
That gate requires both successful collection and successful execution of all
64 shards. A manifest is never a substitute for executing tests. Shard pytest
execution still performs its normal collection of selected nodes and retains
its exit status, assertions, durations, timeout, and failure handling.

This adds one job/install (65 backend dependency installs instead of 64), removes
63 full-suite collections, and leaves the 64 shard assignments unchanged.
It deliberately does not attempt an installed-dependency cache, shard balancing,
PostgreSQL fixture reuse, or shared live-stack execution in the same change.

## Required-check and coverage contract

All eleven required context names remain defined once:

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

Production backend, dependency, shared-fixture, selector, and backend-workflow
changes retain full backend validation under the existing classifier. Existing
narrow/irrelevant cases retain their existing validation contract. No ruleset,
required-context selection, status fabrication, timeout bypass, assertion skip,
or application change is included. The other three inspected workflows remain
unchanged. Any pre-existing scope-policy limitations are not evidence for
skipping required validation in this proposal.

## Local before/after evidence

Initial-proposal measurements, before the additional checkout-tree and node-count
hardening requested for publication. Collected with Python 3.13.16 and
hash-locked dependencies in Codex Cloud, using
the backend workflow's explicit test environment, AI disabled, and no external
providers or customer data. The benchmark executed collection, not the 64 test
shards. Application test sources are unchanged from the baseline above.

| Measurement | Result |
| --- | --- |
| Initial cold collection probe | 22.438s, 1,591 nodes |
| Warm baseline full-collection samples | 13.041s, 12.738s, 13.429s; median 13.041s |
| Candidate manifest producer, including CLI process | 13.041s |
| All 64 consumer CLI processes, sequential total | 7.367s; median 0.112s |
| Manifest size | 191,083 bytes |
| Collection/selection work model | Baseline: 64 × median = 834.616s; candidate: producer + consumers = 20.408s |
| Coverage comparison | All 1,591 baseline node IDs have the identical shard; union is complete and duplicate-free; all 64 shards nonempty |

The modeled collection component decreases by about 97.6%. **This is not an
end-to-end CI speedup claim.** The baseline total is extrapolated from three
collections, not a measured 64-job run. Artifact upload/download, GitHub queues,
the extra dependency install, different runner contention, and actual test
execution are excluded. Baseline collection sampling also excludes the original
selector CLI process startup and selection work, making that estimate conservative.

## Regression validation

Run from the repository root with Python 3.13 and the development environment:

```bash
python -m unittest scripts.tests.test_backend_shard_selector scripts.tests.test_ci_backend_narrow_scope -v
python -m unittest scripts.tests.test_ci_postgres_synthetic_test_scope scripts.tests.test_ci_browser_offline_hm_scope scripts.tests.test_pilot_performance_scope scripts.tests.test_pilot_required_check_preflight scripts.tests.test_pilot_ruleset_evidence -v
actionlint -shellcheck= .github/workflows/backend-premerge.yml
git diff --check
```

Results: 26 focused tests passed; 40 related scope/required-check tests passed;
actionlint 1.7.7 workflow syntax/expression validation passed. ShellCheck is not
included in that actionlint invocation. Regression tests execute the actual final
aggregate Bash for successful, failed, cancelled, skipped, and missing collection
or shard results. Manifest tests verify checksum/commit/shard binding, malformed,
empty, duplicate and partial collections, missing nodes/files, no fallback,
original NUL arguments, exactly-once assignments, and all eleven required check
names. Additional tests create a real synthetic two-parent merge commit and prove
the PR head SHA/tree cannot be substituted for it; staged, untracked and tracked
changes are rejected. Dependency-contract regressions reject a missing producer
edge, a producer-to-shard cycle, or a missing producer dependency in the final gate.

A separate small synthetic integration smoke uses a one-shard manifest of the
24 existing health, authentication/tenant-security, and document API tests,
then executes the consumer's real NUL-delimited pytest invocation. It does not
stand in for full hosted regression validation. Result: **24 passed in 40.31s**,
with one existing FastAPI/Starlette TestClient deprecation warning.

## Hosted before/after benchmark and approval gate

Publishing the branch and opening a Draft PR are authorized; merging and branch
protection changes are not. The existing draft policy intentionally defers the
full backend matrix until ready-for-review or explicit manual dispatch. Opening
the Draft PR therefore does not itself prove all 64 shards executed. Keep the
PR in draft; use `workflow_dispatch` on the candidate branch for approved full
backend measurements without changing that policy.

For hosted verification, collect paired baseline
and candidate workflow runs on the same application/test source, `ubuntu-latest`,
Python 3.13, locked dependencies, event type, and readiness state. Pin and record
both SHAs, workflow run/attempt IDs, and cache state. Use at least five completed
paired runs; report cold and warm cache samples separately and keep cancelled,
failed, and rerun attempts separate. Do not trigger this expensive experiment
until the local proposal is approved.

For each pair record:

- Backend producer and each shard: queue time, checkout/setup/install, full
  collection or manifest transfer/selection, test time, and job duration.
- Overall backend gate latency and aggregate backend runner-minutes; median
  and observed p95, with the small sample size stated.
- Exactly equal collected node IDs, hash assignments, and executed node
  outcomes (pass/fail/expected-fail/skip), accounting for existing DB-only tests
  that belong to the mandatory dedicated PostgreSQL workflow. Do not relabel
  skipped database tests as executed backend passes.
- Full required-check results on the exact candidate SHA: all eleven names,
  with the unchanged PostgreSQL groups, browser/operational validation, security
  scans, migration checks, and production policy running as their scope requires.

Acceptance: identical coverage and outcomes, all eleven required checks green,
at least 90% reduction in the aggregate collection/selection component, reduced
total backend runner-minutes, and no more than 5% regression in median backend
gate latency. Investigate p95 regressions and queue/cold-cache confounders rather
than averaging them away. Reject or revise the proposal if the serial producer
and artifact costs erase the savings or make the critical path materially worse.

Compare Full Backend wall time with the approximately 44-minute hosted median
from #553 (a 5% historical guardrail is approximately 46.2 minutes). Compare total
candidate backend runner cost **including the new producer** with the approximately
505 shard runner-minutes recorded for PR #864, as well as with the fresh paired
baseline. Record the differing scopes explicitly: the historical 505 figure
contains 64 shard jobs, while the candidate comparison must include those jobs
plus collection. No hosted speedup or runner-minute saving is established yet.

On an unmerged synthetic proof branch, confirm producer collection failure,
artifact/digest/commit mismatch, failed or cancelled shard execution, and missing
outputs cannot produce a successful `Backend tests` check. Verify failed-job-only
reruns can use the original successful producer artifact; verify expired-artifact
failure and successful rerun-all recovery. No branch protection bypass or merge
is needed for any of these observations.

## Risks and rollback

- The new producer serializes dependency setup before matrix allocation and may
  increase gate wall-clock latency even while reducing aggregate work. Hosted
  acceptance, not local extrapolation, decides whether to adopt it.
- Artifact availability becomes a backend CI dependency; failures remain red.
  One-day retention bounds storage but requires rerun-all after expiration.
- Collection assumes identical code, dependencies, and collection environment
  in producer and shards. Tests enforce explicit environment parity. Future
  environment-dependent parametrization must preserve this contract or return
  to per-shard collection; missing selected tests still fail pytest.
- A hash detects transfer/substitution errors against the producer's trusted
  output; it is not a security boundary against someone authorized to rewrite
  the workflow itself. Normal review and all required checks remain necessary.

Rollback is reverting the workflow and selector proposal to the original
per-shard collection path. No database migration, dependency change, production
deployment, insurance-claim mutation, or data migration is involved. Hosted
Actions and artifact/rerun behavior remain unverified pending approved execution.
