# Main branch protected check matrix

## Source of authority and dated evidence

- GitHub repository `eh3aneba/maritime-claims-platform`, active repository
  ruleset **Protect main** (`20842512`).
- Exact intended required names are defined by
  `scripts/pilot_ruleset_evidence.py:EXPECTED_CONTEXTS`; do not infer
  GitHub check contexts from workflow names.
- Issue [#461](https://github.com/eh3aneba/maritime-claims-platform/issues/461)
  is **closed**. Its latest dated record, **2026-10-12**, reports live ruleset
  readback of **11/11 exact required contexts**, strict/up-to-date checks,
  squash-only merges, linear history, resolved conversations, protected
  deletion/non-fast-forward, and zero bypass actors.
- The same issue records the synthetic-only
  [PR #707](https://github.com/eh3aneba/maritime-claims-platform/pull/707)
  **RED / GREEN** experiment on separate exact heads of one open PR:
  the mandatory `Production environment policy` check failed in RED
  and the GitHub mergeability state was `blocked`; after repair that check
  succeeded and mergeability was `clean`. No forbidden merge attempt was
  performed, and no customer data was used.
- **Evidence boundary:** the above is a *historical, dated issue record*,
  not a fresh live admin ruleset readback during each PR. Operators
  re-run `scripts/pilot_ruleset_evidence.py` and
  `scripts/pilot_required_check_preflight.py` on the protected
  release candidate; new governance failures reopen investigation.
  Closed #461 does not mean customer Pilot GO.

## Eleven stable required contexts

Only the following exact context names should be in `Protect main`:

| # | Required exact context | Source / purpose |
| --- | --- | --- |
| 1 | `Backend tests` | Full Backend Pre-Merge's stable classification/aggregation |
| 2 | `PostgreSQL migration chain` | Continuous Integration migration job |
| 3 | `Frontend typecheck and build` | Continuous Integration frontend |
| 4 | `Docker Compose validation` | Continuous Integration Compose |
| 5 | `Scoped CI gate` | Stable `if: always()` gate for optional CI jobs |
| 6 | `PostgreSQL concurrency gate` | Stable aggregate for selected PostgreSQL concurrency jobs |
| 7 | `Operational performance gate` | Stable aggregate for live-stack performance checks |
| 8 | `Production dependency audit and SBOM` | Supply Chain Security |
| 9 | `Secret history scan` | Supply Chain Security |
| 10 | `Container image vulnerability scan` | Supply Chain Security |
| 11 | `Production environment policy` | Production Deployment Policy |

The corresponding six **workflow** names (shown in PR run lists) are
`Full Backend Pre-Merge`, `Continuous Integration`,
`PostgreSQL Concurrency Regression Suite`, `Operational Performance Smoke`,
`Supply Chain Security` and `Production Deployment Policy`.
**Workflow success alone is not a substitute for exact required-check
identity and independently reviewed operations evidence.**

## Path-aware execution

- `Scoped CI gate` aggregates **conditional** `Dependency lock
  consistency` and `Design partner browser E2E`. Do **not** globally
  require the conditional names; unrelated changes may legitimately skip
  them while the aggregate enforces selected jobs.
- `PostgreSQL concurrency gate` aggregates the selected PostgreSQL
  shard/group matrix. Do **not** globally require dynamic individual group
  names; ambiguous/shared runtime changes fail closed to broader coverage.
- `Operational performance gate` aggregates the live-stack smoke result.
  A narrow documentation change may skip expensive implementation work
  and still require the always-emitted aggregate.
- `Backend tests` aggregates the relevant full-backend policy on ready
  PRs. **A green backend aggregate does not prove all 64 shards ran**
  when the diff classifier intentionally selected a narrower path.
- Security and deployment checks must not be disabled to work around
  an unrelated, required-failing change.

## Periodic verification and safe response

1. Read back **current** ruleset metadata from GitHub using approved
   operator tooling; compare name sets **exactly** to the eleven names
   in `EXPECTED_CONTEXTS`, require zero duplicates, unexpected names or
   bypass actors, and verify strict, branch and history protections.
2. On the **exact current PR head**, verify each required check comes
   from the intended GitHub Actions source and completed successfully;
   check selected backend/shard coverage for the code changed.
3. Preserve the intentional synthetic red/green #707 record as a proof
   artifact; **never merge its controlled proof branch**.
4. A new required context must first be available on `main` and
   always emitted for any protected PR; change rulesets only through an
   authorized Admin surface and perform red/green proof without bypass.
5. Record exact SHA, failed/green check IDs, operator ticket/reviewer
   acceptance and any remaining P0 gaps before any operational release.

## Scope boundary

#461's repository protection evidence is **separate** from #487 non-root
customer Evidence migration, #653 independent database+Evidence recovery
and release rehearsals, #752 local LLM readiness, #647 H&M pilot
acceptance, and conditional #652 SFTP real-server acceptance. None of
those open operational items can be made green by altering a GitHub
status-check matrix. Real-data Pilot GO remains NO until separately
approved.
