# ADR-155: Automated legal-hold proposals are non-self-authorizing

## Status
Accepted for Phase 17.2-B implementation.

## Context
Phase 17.2-A established tenant retention policy, formal claim legal holds and a fail-closed disposal eligibility preview. The next enterprise requirement is to accept preservation signals from future rules, webhooks, AI-assisted review, investigations or external notices without allowing those systems to become legal authority.

A machine-detected phrase, rule result, webhook event or AI classification can be useful evidence that preservation should be reviewed. It is not, by itself, a reliable legal conclusion that a formal hold must be imposed or released. At the same time, ignoring a credible pending signal while disposal proceeds would create an unacceptable race.

## Decision
Phase 17.2-B introduces an append-only `LegalHoldProposal` lifecycle.

1. Automated/internal callers can ingest a signal only as a **pending proposal**.
2. Raw source references and transport payloads are not stored. The platform retains a source-reference fingerprint and canonical payload hash plus a bounded review reason.
3. Signal identity is deterministic. Exact replay is idempotent; reuse of the same identity with changed payload or changed proposal semantics fails closed.
4. A pending proposal blocks disposal eligibility with `pending_legal_hold_proposal`. This is a temporary preservation guard, not a formal legal hold.
5. Only a local application Admin passing the tenant's current MFA policy may **activate** or **reject** a pending proposal.
6. Activation creates exactly one ordinary `ClaimLegalHold`, records the exact hold id on the proposal, and leaves formal hold release under the pre-existing Admin + MFA flow.
7. Rejection is terminal and auditable. An activated proposal cannot be rejected, and a rejected proposal cannot later be activated.
8. Proposal APIs expose tenant-scoped review/decision surfaces only. This phase does not expose a provider-specific public webhook transport.

## Authority boundary
- Database organization membership and local `User.role` remain authoritative.
- Rules, webhooks, AI and external notices have **proposal authority only**.
- Proposal ingestion has no route to archive, purge, soft-delete, hard-delete, activate a formal hold or release one.
- Formal activation and release remain human-governed local Admin actions constrained by current MFA policy.
- A proposal cannot override an existing active formal hold.

## Preservation semantics
A pending proposal is intentionally conservative. Even where a final claim is beyond its ordinary retention period and tenant disposal is enabled, disposal preview remains ineligible until the proposal is either activated or rejected. If activated, the resulting active formal hold continues to block disposal. If rejected and there is no other blocker, ordinary retention logic resumes.

## Consequences
This design creates a stable ingestion contract for later transport integrations without coupling retention authority to any specific source. A future webhook, rules hook or AI-assisted detector can call the proposal service while remaining incapable of directly mutating preservation authority.

The next tranche may add provider-specific or rules-driven signal adapters that call this service. Controlled archival/hard disposal remains a separate later tranche and must consume both formal holds and pending proposal blockers.

## Rejected alternatives
- **Automatically create a formal hold when a signal arrives.** Rejected because the source would become self-authorizing legal authority.
- **Allow AI confidence above a threshold to activate a hold.** Rejected because confidence is not legal authority.
- **Let pending proposals coexist with disposal eligibility.** Rejected because disposal could race a preservation review.
- **Store full webhook/email payloads for convenience.** Rejected because the retention domain needs provenance identity, not unnecessary copies of potentially sensitive transport content.
- **Allow proposal rejection to release an already activated hold.** Rejected because formal hold release is a distinct governed decision.

## Follow-up
A later bounded tranche can add source adapters and controlled automated proposal creation from selected events. Physical archival/disposal must remain separately reviewed and must never bypass pending proposals or active formal holds.

Refs #25, #294.
