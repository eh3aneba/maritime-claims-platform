# Claims Workbench Architecture

## Purpose
Phase 12J provides a tenant-scoped portfolio attention read model for claims handlers and managers. It answers one operational question: **which claims need human attention next, and which existing controlled source caused that attention?**

It is not a claim-merits engine. The workbench does not determine or mutate coverage, liability, causation, recoverability, reserve, settlement, payment, legal rights, ClaimFacts or correspondence.

## Source model
The foundation calculates the workbench at read time from current tenant-scoped source state. It does not persist a second authoritative portfolio table.

Current source adapters use:
- latest `SeverityReserveSnapshot` + severity evaluation;
- latest `RecoveryTimebarSnapshot` + time-bar evaluation;
- open `FinancialFlag` rows;
- latest `ClaimIntelligenceSnapshot` items limited to missing-evidence/conflict attention;
- open `ClaimTask` rows;
- pending `AIProductionDecisionLog` review metadata;
- governed Claim Q&A operational failure/fallback metadata.

For snapshot-based modules, only the highest `snapshot_version` for each tenant/claim participates. Older snapshots remain historical evidence but cannot silently outrank current source state.

## Deterministic ranking contract
Ranking contract `12J.1` assigns bounded workflow weights to existing controlled signals. Examples include critical handling severity, a near candidate time-bar, an overdue/high-priority task, open financial-review flags, missing evidence/conflicts and pending different-human AI review.

The score is **workflow priority only**. No LLM or predictive model participates in the foundation ranking.

Each factor exposes:
- source type/id/hash;
- attention category and safe label;
- deterministic weight and priority hint;
- optional date plus explicit semantics;
- deep link back to the source workflow.

`candidate_timebar` dates are always labelled as candidate dates. `authoritative_task_due` is reserved for an existing ClaimTask due date. The workbench never upgrades a candidate legal date into an authoritative deadline.

The rank hash is SHA-256 over the ranking version, claim workflow state and normalized factor lineage. Unchanged controlled source state therefore produces the same rank hash.

## Tenant and role scope
Every source query is constrained by `organization_id` before aggregation. Admins and claims managers receive the tenant portfolio. Claims handlers receive only claims assigned to their own `handler_id`.

## API
- `GET /api/v1/claim-workbench` — metrics plus first ranked rows.
- `GET /api/v1/claim-workbench/queue` — bounded pagination and operational filters.
- `GET /api/v1/claim-workbench/claims/{claim_id}` — one visible claim's normalized lineage.

The API intentionally omits raw incident descriptions, raw document/evidence text, prompts, questions, provider responses and synthesized answers.

## Failure and authority boundary
A source module may be absent for a claim; that simply contributes no factor. The workbench never invents missing evidence, a severity, a time-bar or a financial conclusion. `insufficient_evidence` time-bar evaluations do not create a candidate-date factor.

No workbench read changes source records. Human action continues inside the linked source workflow.
