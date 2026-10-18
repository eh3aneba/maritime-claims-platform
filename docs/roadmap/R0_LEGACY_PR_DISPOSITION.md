# R0-04 — Historical PR reconciliation (2026-10-18)

This is **disposition of obsolete open branches**, not deletion of audit
records and not proof of acceptance of a future product feature.
Observations were compared with current `main` GitHub file blobs and
the current source modules. Do not revive stale patches without a
fresh exact-head change, measurement and mandatory check gate.

| PR | Purpose | Current-main verification | Disposition |
| --- | --- | --- | --- |
| [#554](https://github.com/eh3aneba/maritime-claims-platform/pull/554) | Reuse Evidence family in PostgreSQL service-executor concurrency | `test_external_document_source_due_tick_service_executor_concurrency_postgres.py` contains `_seed_bound_family` and `_seed_dispatch_revision`; current concurrency workflow contains `--durations=10`, with more recent group routing | **CLOSED WITHOUT MERGE** (superseded) |
| [#562](https://github.com/eh3aneba/maritime-claims-platform/pull/562) | Reuse review decision/handoff race fixtures | Decision and handoff test modules present on `main`; matching Git blobs; workflow matrix has since evolved | **CLOSED WITHOUT MERGE** (superseded) |
| [#565](https://github.com/eh3aneba/maritime-claims-platform/pull/565) | Reuse refresh authorization fixture | Main has the same helper-module blob and includes `_seed_authorized_refresh` / `include_refresh_execution=False`; further main improvements exist | **CLOSED WITHOUT MERGE** (superseded) |
| [#641](https://github.com/eh3aneba/maritime-claims-platform/pull/641) | Refresh branch protection documentation | Its historical text says four checks active and red/green proof not yet complete; superseded by #461's dated 11-check readback and proof in #707 | **CLOSED WITHOUT MERGE** (stale) |
| [#707](https://github.com/eh3aneba/maritime-claims-platform/pull/707) | Synthetic red/green branch protection proof | #461 records failed mandatory policy check → blocked and repaired same PR → clean, no forbidden merge | **OPEN, INTENTIONAL, NEVER MERGE** |
| [#746](https://github.com/eh3aneba/maritime-claims-platform/pull/746) | R2 claim-folder physical inventory | Latest checked head had five workflows success but `Full Backend Pre-Merge` workflow failure; branch is now behind latest `main` | **OPEN — HOLD / TRIAGE UNDER R2**, not an R0 closure requirement |

## What these decisions do not establish

- Closed old Draft PRs are **not** treated as additional merged
  functionality or an objective CI queue optimization benchmark.
- Closing #641 does not mutate any GitHub protection setting; the
  replacement `docs/product/MAIN_REQUIRED_GATES.md` records **dated**
  2026-10-12 evidence. The active ruleset must still be re-read for a
  final release candidate.
- #707 remains deliberately unmerged, even if its last repaired check
  run is green. The initial failing proof is retained in #461.
- #746 remains outside accepted R0 scope. Investigate and repair its
  exact-head backend run **before** separately authorizing an R2 merge.

## R0 exit tracking

The GitHub stale-PR disposition portion of R0-04 is **COMPLETE**.
R0 itself stays **IN PROGRESS** pending product/buyer/jurisdiction
decisions, precise ownership and independent acceptance, and any other
unfinished R0-03/R0-05 requirements.
