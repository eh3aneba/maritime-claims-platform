# ADR-156 — Signed preservation-signal intake remains proposal-only

## Status
Accepted for Phase 17.2-C.

## Context
Phase 17.2-A established tenant retention policy and formal claim legal holds. Phase 17.2-B added non-self-authorizing `LegalHoldProposal` records so automated sources can surface preservation concerns without receiving legal authority.

The next enterprise-readiness gap is a controlled way for an external system such as outside-counsel workflow, regulatory-notice service, or approved internal integration to deliver a preservation signal into that proposal queue.

A generic inbound command webhook would be too broad. It could accidentally become an alternate authority path for legal holds or future disposal actions.

## Decision
Introduce a dedicated tenant-scoped `PreservationSignalProfile` and a narrow signed intake endpoint.

- Profiles are disabled by default.
- Profile creation, mutation and key rotation require local Admin authority and the tenant's current MFA policy.
- Signing secrets are derived from the application master secret plus profile salt/version; raw secret material is returned only at creation/rotation and is never persisted.
- HMAC-SHA256 covers the exact raw request body together with timestamp and key version.
- Requests outside a five-minute freshness window fail closed.
- Key rotation keeps only a bounded previous-key grace window.
- The profile allowlists the legal-hold source categories it may recommend: `litigation`, `regulatory`, `investigation`.
- A signed signal can create only a pending `LegalHoldProposal` with `source_kind=webhook`.
- Proposal identity is `profile_id + external signal_id`; exact replay is idempotent and changed semantics under the same identity fail closed.
- Raw transport payload and raw source identifiers are not persisted by the proposal layer; only hashes/fingerprints and the bounded preservation reason are retained.
- A pending proposal blocks disposal eligibility until a local Admin activates or rejects it.
- Formal legal-hold activation/release remains the existing human-authoritative workflow.

## Consequences
The platform can now accept machine-originated preservation notices without delegating legal authority. A compromised integration can at worst create bounded preservation proposals and pause disposal eligibility; it cannot release a hold or destroy evidence.

The design deliberately prefers false-positive preservation over false-negative destruction. Operational controls can disable or rotate a profile without rewriting proposal history.

## Non-goals
This phase does not add AI/rules self-activation, automatic legal-hold release, generic inbound commands, archival, purge, object deletion, soft deletion, hard deletion, or a disposal worker.

## Follow-up
A later Phase 17.2-D may introduce a separately governed disposal authorization/execution workflow. It must consume the current retention policy, active formal holds, pending proposals, and immutable approval/audit evidence; timer expiry alone must never become deletion authority.
