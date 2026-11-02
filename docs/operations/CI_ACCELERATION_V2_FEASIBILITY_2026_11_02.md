# CI Acceleration v2 — one matched-source feasibility pair

This is an execution record for the frozen proposal in Draft
[#866](https://github.com/eh3aneba/maritime-claims-platform/pull/866), not a new
implementation or permission to merge. The proposal's
[acceptance protocol](https://github.com/eh3aneba/maritime-claims-platform/blob/998858f31d8c6ff8b8a2fe4b1184d787975efdf3/docs/operations/CI_ACCELERATION_V2.md)
still requires at least five completed pairs and coverage, safety and performance
evidence. One successful pair cannot satisfy that protocol.

## Source and execution contract

- Baseline: `fa2c471463f5aecb988f89e791aae359385227e4` (verified main).
- Candidate: `998858f31d8c6ff8b8a2fe4b1184d787975efdf3` (unchanged Draft #866).
- Both application/test/lockfile trees:
  `f239abea5a30d08e3b5d7a3c4508ff91fa55057a` at `apps/api`.
- The narrow classifier is unchanged. Both use the existing explicit
  `workflow_dispatch` path, all 64 shards, and existing required check names.
  No Draft state, branch protection, source commit or workflow was modified.
- Baseline first; candidate only after baseline success and a renewed frozen-head
  and competing-work check. No automatic reruns or cache resets. Failed attempts
  remain separate; they must not be relabeled successful measurements.
- No running repository workflow existed at preflight. Four September queued
  runs had zero jobs; they were recorded, not cancelled. In-progress polling and
  a recent-workflow activity audit record observed interference. This does not
  establish identical hardware, cache state or global GitHub runner contention.

The prior #867 result (42.53 minutes / 486.18 shard runner-minutes) is retained
as historical engineering evidence, not substituted for this baseline: #867
adds bootstrap tests and overlapped other validation. Issue #553 / PR #864's
approximately 44-minute median and 505 shard runner-minutes also remain reference
measurements, not new acceptance results.

## Observed results

Both runs completed successfully on their recorded first attempts: all 64 shard
jobs and the Backend gate passed; the candidate collection producer passed.

| Observation | Baseline | Candidate |
| --- | ---: | ---: |
| Workflow run | [41386381744](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41386381744) | [41389632800](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41389632800) |
| Dispatch to last job, minutes | 34.42 | 36.65 |
| Shard runner-minutes | 511.80 | 469.88 |
| Producer runner-minutes | 0.00 | 0.83 |
| Backend runner-minutes including producer | 511.80 | 470.72 |
| Dependency-install step minutes, aggregate | 13.30 | 12.72 |
| Artifact-transfer step minutes, aggregate | 0.00 | 0.85 |
| Dispatch to first shard start, minutes | 0.30 | 1.08 |
| First-to-last shard start spread, minutes | 20.07 | 17.15 |

The observed backend cost including producer was **8.03% lower**,
while wall time was **6.49% higher**. These are one-pair observations,
not established median/p95 changes or causal savings. Elapsed job minutes are
not a billing statement. Dependency installation still occurs in every shard;
the candidate adds a producer installation rather than sharing environments.

Shard 62 started 3.87 minutes after baseline dispatch versus 17.25 minutes after
candidate dispatch, and ran for 18.68 versus 19.30 minutes. It became the
candidate's final shard. This scheduling difference is material context; the data
does not isolate workflow effects from queue placement, cache or runner variance.
No competing repository execution was observed in polling or the end-of-pair
activity audit. Four old queued workflows still had zero jobs; none was cancelled.

The observed wall change is above the proposal's 5% median-wall guard number,
but one pair does not establish that median. **Keep #866 Draft; do not adopt on
this sample.** Investigate latency and complete the required evidence rather
than changing shards, tests or acceptance thresholds.

[Preflight](validation/ci-v2-pair-2026-11-02-preflight.json),
[baseline receipt](validation/ci-v2-pair-2026-11-02-baseline.json),
[candidate receipt](validation/ci-v2-pair-2026-11-02-candidate.json),
[computed observation](validation/ci-v2-pair-2026-11-02-observation.json),
[interference audit](validation/ci-v2-pair-2026-11-02-interference-audit.json),
[artifact metadata](validation/ci-v2-pair-2026-11-02-artifact-metadata.json), and
[local node reference](validation/ci-v2-pair-2026-11-02-local-node-reference.json)
are preserved. The uploaded archive is bound by API metadata to the exact
candidate head; its contents were not independently downloaded by this agent.
Its recorded expiry is **2026-11-03 08:09 Asia/Tehran**. Expired/missing artifacts
must fail closed; do not substitute another run's data.

Recompute the observation from the repository root:

```bash
python docs/operations/validation/ci_v2_pair_observation.py \
  docs/operations/validation/ci-v2-pair-2026-11-02-preflight.json \
  docs/operations/validation/ci-v2-pair-2026-11-02-baseline.json \
  docs/operations/validation/ci-v2-pair-2026-11-02-candidate.json
```

## Offline validation and coverage limits

The [analyzer](validation/ci_v2_pair_observation.py) reads saved API snapshots
only. It makes no network requests and cannot dispatch, cancel, merge, approve
or change policy. Its first-attempt/full-dispatch contract rejects incomplete,
failed, skipped or duplicate shards, wrong commits, missing gates/producer,
missing/duplicate required steps, broken timestamps, mismatched source trees and
overlapping pairs. It includes the new producer in candidate backend cost and
records serial delay before the first shard. A combined selection/pytest step
is explicitly **not** collection-only timing.

Run the fixed-clock invented-DTO regression suite:

```bash
python docs/operations/validation/test_ci_v2_pair_observation.py -v
```

**11 tests passed.** The actual incomplete baseline snapshot was also rejected
with `run_not_successful`; no success metrics were produced from it.

An isolated archive of the exact baseline source collected **1,591 unique IDs**
locally, with 13–39 IDs assigned per shard and no empty shard. The local reference
records a sorted-node-set digest and locally predicted candidate manifest digest.
It is not a hosted manifest, proof of identical hosted collection, or a claim
that 1,591 tests passed. Database-only skips/xfails and their mandatory dedicated
PostgreSQL validation must not be relabeled as Backend passes.

Detailed Actions logs remain blocked at the known storage redirect. No denied
download was retried and no signed download URL was stored. Artifact metadata
can describe an uploaded archive, but its archive digest does not independently
verify the manifest's node list. The analyzer therefore leaves exact hosted
node/outcome equivalence, collection-only savings, cache/image parity, median,
p95 and overall acceptance **unverified**, even if all jobs succeed.

## Next evidence before adoption

1. Obtain permitted read-only log/artifact access and compare exact collected
   node IDs, assignments and outcomes; inspect actual producer/consumer identity
   and digest evidence. Preserve required checks and fail closed on discrepancies.
2. Complete the documented paired-sample/cold-versus-warm and hosted negative
   artifact/producer/rerun evidence. Account for producer/transfer costs and
   queue variation. Do not weaken the 90% component or 5% median-wall criteria.
3. Review the frozen Draft with this evidence. No merge or review-state change
   is authorized by a timing result. H&M expert acceptance, signature-freshness
   policy and Customer Pilot NO-GO remain separate and unchanged.
