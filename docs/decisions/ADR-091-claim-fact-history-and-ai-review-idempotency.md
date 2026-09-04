# ADR-091 — Canonical ClaimFact history and AI review retries must preserve human authority and reversible provenance

Status: Accepted for Phase 13.2 implementation

## Context

Phase 13.1 established one canonical `ClaimFact` read model that can be created from either human-reviewed intake evidence (`intake_review`) or human-approved AI extraction (`ai_review`). The current row is intentionally unique per organization, claim and field path so downstream chronology, technical and financial workflows have one unambiguous approved value.

Two maturity gaps appear when that fact is reviewed again. First, the AI-review update path previously replaced `source_extraction_id` without also switching the complete provenance tuple away from `intake_review`, which can violate the database provenance constraint. Second, a later rejection of an AI extraction that superseded a valid intake fact has no reliable way to recover the earlier canonical state if only the current row is retained. Audit log prose is useful evidence of activity, but it is not a typed canonical-fact history and must not become a hidden rollback database.

Individual review requests can also be replayed by browsers, clients or networks. Re-executing an identical successful request must not create duplicate feedback, duplicate audit entries or artificial `ClaimFact.version` increments. At the same time, a reviewer must retain the ability to make a deliberate later decision, including approve → edit, approve/edit → reject, or a same-value re-review supported by new reasoning.

Concurrent reviewers add a final requirement: canonical fact mutation must be serialized so two extractions cannot race to become the current fact from stale application state.

## Decision

1. `claim_facts` remains the current, fast canonical read model. No AI candidate becomes authoritative without an explicit human review action.
2. Add append-only `claim_fact_revisions`. Every new or changed `ClaimFact` creates one immutable typed snapshot containing value, version, provenance kind, source extraction/text extraction, source document/segment and human approver/time.
3. Record revisions at the SQLAlchemy session boundary (`before_flush`) so deterministic intake review and AI review use the same history rule. Callers must not be required to remember separate snapshot logic.
4. Migration 0066 seeds one revision from every current pre-existing `ClaimFact`. Historical states from before 0066 are not reconstructed from audit logs because those logs were not designed as a canonical typed fact store. Therefore a pre-0066 fact with `version > 1` has only its current state structurally backfilled.
5. When an approved/edited AI extraction supersedes a current fact, replace the entire provenance tuple atomically: set `provenance_kind=ai_review`, set `source_extraction_id`, clear `source_text_extraction_id`, and update the source document/segment and human approval metadata.
6. When the currently promoted AI extraction is later rejected, restore the latest earlier revision that is still valid. An `intake_review` revision is independently human-approved and is restorable. An earlier `ai_review` revision is restorable only while its source extraction remains human `approved` or `edited`. If no valid prior revision exists, remove the current fact.
7. Restoration creates a new current version rather than rewinding the version counter. History therefore remains monotonic and explains both supersession and restoration.
8. Treat an exact semantic replay as idempotent when current extraction status/value and the latest feedback action/value/reason already equal the incoming decision. The replay creates no new feedback, audit entry or fact version.
9. A materially different decision remains intentional. In particular, changing action/value is a new review; supplying different reasoning for the same value is also treated as a deliberate re-review and is appended to feedback/history.
10. Serialize canonical fact mutation per claim with a PostgreSQL row lock before locking the individual extraction. Mutation endpoints expire earlier authorization/validation reads so the locked select cannot silently reuse stale identity-map attributes after waiting for another reviewer.
11. Preserve existing non-promotable boundaries. AI opinions/inferences and paths concerning cause, coverage, liability, fraud, reserve, settlement, recoverability, policy/contract interpretation and controlled commercial/technical list items do not become canonical facts merely because they were reviewed.
12. This decision does not create autonomous approval, coverage, liability, causation, reserve, settlement, payment or legal authority. Human review remains the authority boundary.

## Consequences

- Intake → AI supersession becomes database-constraint-correct and source lineage remains explicit.
- A later human rejection can restore the last still-valid approved fact instead of silently losing prior authoritative evidence.
- Network/client retries no longer inflate feedback or fact versions, while genuine re-review remains possible.
- Downstream consumers continue reading one current `ClaimFact`; they do not need to reconstruct authority from revisions.
- PostgreSQL review mutations become more conservative because they serialize at claim scope. This is intentional for correctness; throughput can be revisited only with equivalent conflict guarantees.
- Pre-0066 historical versions cannot be reconstructed with the same structural assurance. The migration records the current state only and this limitation is explicit rather than fabricating history from audit text.
- Phase 13.2 UX may expose current provenance and review history, but the revision table is an integrity mechanism, not a new top-level product feature.
