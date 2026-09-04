# ADR-099 — Technical investigation decision lineage

## Status
Accepted for Phase 13.5A.

## Context
The existing Technical Review matrix is assembled from canonical ClaimFacts, active deterministic technical issues and human-reviewed workshop evidence. It correctly distinguishes source opinions from confirmed cause, but the assembled matrix is ephemeral: evidence changes can replace the visible investigation state without preserving whether an earlier handler disposition applied to the same evidence.

A production claims workflow needs durable human reasoning lineage without turning the application into an autonomous causation engine or creating a second mutable source of truth.

## Decision
1. The current Technical Review topic remains **computed from current reviewed/canonical evidence**. GET requests do not persist a mutable technical-state record.
2. Technical rule topics retain their existing stable `issue_key`. Workshop-opinion topics use `workshop_opinion:<extraction_id>` rather than list position.
3. Each current topic receives a canonical SHA-256 `state_fingerprint` over the evidence and investigation content visible to the handler.
4. `state_version` is derived from append-only decision lineage: no prior decision is version 1; unchanged evidence retains the prior version; changed evidence advances the displayed version relative to the latest decision.
5. Human dispositions are append-only and hash-chained in `technical_investigation_decisions`.
6. Allowed dispositions are deliberately investigation-oriented: `keep_open`, `supported_for_investigation`, `not_supported`, and `needs_more_evidence`. There is no `confirmed_cause` action.
7. Decision writes include the exact `expected_state_fingerprint` and `expected_state_version`. The server obtains a claim-level database lock, recomputes the current topic and rejects stale writes with HTTP 409 semantics.
8. Exact semantic replay on the same evidence state is idempotent. Changing a prior disposition, or recording a new disposition after evidence has evolved, requires explicit re-review confirmation.
9. Historical decisions remain visible when a topic disappears or changes; history never transfers silently to a different evidence state.
10. Tenant/claim/topic scope is enforced on every history and write path.

## Authority boundary
A technical disposition records a handler's investigation treatment of the evidence. It does **not** establish proximate cause, policy coverage, liability, negligence, unseaworthiness, workmanship responsibility, fraud, recovery entitlement, reserve, settlement or any legal outcome. Workshop, surveyor and maker statements remain source opinions unless and until independently evaluated by a human, and even a recorded investigation disposition is not a legal or coverage determination.

## Consequences
- Technical evidence evolution becomes observable as `current` versus `stale` rather than silently replacing prior reasoning.
- GET remains side-effect-free and no duplicate mutable causation state is introduced.
- Phase 13.5B can add controlled operator disposition/re-review UX to the existing Technical Review page without changing the underlying authority model.
- Browser acceptance can later prove evidence change → stale prior disposition → deliberate human re-review on MT ORION.
