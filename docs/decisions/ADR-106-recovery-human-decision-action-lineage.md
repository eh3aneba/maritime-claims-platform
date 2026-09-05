# ADR-106 — Recovery human decision and action lineage

## Status
Accepted for Phase 13.7B.

## Context
Phase 13.7A established the canonical Recovery / Time-Bar workspace with append-only human counterparty context and alternative human-defined time-bar scenarios. The remaining maturity gap is operational: a claims handler needs to record whether a recovery path is being pursued, monitored, not pursued, or closed, and then preserve the correspondence/actions and externally supplied response status that follow.

That workflow must not become a second causation, liability, entitlement, settlement, payment, or legal-outcome authority. It must also remain safe when the human counterparty/source context evolves after a decision was recorded.

## Decision
The existing `recovery_timebar` capability remains the canonical Recovery workspace. Phase 13.7B adds two append-only records within that authority boundary:

1. **Recovery pursuit decision lineage**
   - Each logical recovery path has a stable `decision_key` and immutable numbered versions.
   - A version records an explicit human disposition: `pursue`, `monitor`, `do_not_pursue`, or `close`.
   - Every version binds the exact immutable `RecoveryCounterparty` record reviewed by the human operator.
   - Revisions require the latest `decision_hash` and create a new row linked through `supersedes_id` and `previous_decision_hash`.
   - A revised decision must stay on the same logical counterparty path; it cannot silently switch to another counterparty.
   - Only one current decision path may exist for a logical counterparty.

2. **Recovery action / correspondence lineage**
   - Actions are append-only and numbered per `decision_key`.
   - Each action binds the exact current decision version/hash at the time it was recorded.
   - The record may describe correspondence, a human-approved demand already created outside platform authority, follow-up, an external response, or an internal note.
   - Direction, occurred date, human summary, source reference, optional externally supplied status, and optional external response date are preserved.
   - `previous_action_hash` creates a tamper-evident chronological hash chain.

## Stale-context rule
A recovery decision is current only while its bound counterparty version remains the latest logical counterparty record and that counterparty's bound document/source context remains usable/current.

If the counterparty or its source evolves:

- the historical decision remains visible and immutable;
- its context state becomes `stale` or `source_unavailable`;
- new actions are blocked;
- the user must deliberately create a new decision version bound to the current counterparty record before continuing the action log.

This is a fail-closed control. Source evolution never rewrites an earlier decision or action.

## Authority boundary
The platform records human claim-handling decisions and actions. It does **not**:

- determine liability, fault, causation, legal entitlement, or recoverability;
- select a party against whom recovery legally lies;
- generate or approve demand content;
- decide settlement terms or payment;
- infer an external response or response date;
- automatically change `pursue`, `monitor`, `do_not_pursue`, or `close` state.

Any demand/action described in the log is a human-entered record of an externally approved/performed step, not an autonomous platform act.

## Concurrency and audit
- Decision writes use optimistic concurrency through `expected_decision_hash`.
- Action writes require the current decision hash.
- Claim-level locking prevents a concurrent counterparty revision from racing a decision/action write.
- Decision versions and actions are hash chained and audit logged.
- Prior rows are never updated in place.

## RBAC and tenancy
Current Recovery editors (`ADMIN`, `CLAIMS_MANAGER`, `CLAIMS_HANDLER`) may record the human disposition and append actions. Tenant isolation is inherited from the claim-scoped Recovery routes. This ADR does not grant autonomous legal, settlement, or payment authority to any role.

## UX
The EN/FA/RTL Recovery maturity workspace exposes a dedicated Recovery decision/action panel inside the existing canonical surface. Stale/source-unavailable decisions are visibly marked and cannot accept new actions until a deliberate decision revision is recorded.

## Consequences
### Positive
- Operational recovery work becomes auditable without creating a new platform authority.
- Historical decisions remain defensible when evidence/counterparty context evolves.
- Correspondence and response chronology is explicit and tamper-evident.
- Recovery closure/reporting in Phase 13.7C can consume a single explicit current human state.

### Trade-offs
- The platform intentionally does not automate pursue/close decisions.
- A source/counterparty evolution requires an explicit human refresh before more actions can be logged.
- The action log records externally supplied status rather than inferring it from correspondence.
