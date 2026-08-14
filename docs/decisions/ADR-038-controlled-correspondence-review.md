# ADR-038: Controlled correspondence review and manual dispatch recording

- Status: Accepted
- Date: 2026-08-14

## Context

Claim teams need formal correspondence linked to evidence, document requirements
and follow-up tasks. A simple send button would create legal, confidentiality and
operational risk, while mailbox ingestion introduces separate consent, provider
and retention concerns.

## Decision

Introduce a tenant-scoped claim correspondence record with explicit direction,
kind, sensitivity and lifecycle state. Outbound content must be reviewed by a
Claims Manager or Admin before a user can manually record it as sent externally.

Approval freezes a deterministic content hash. The sent transition requires an
explicit confirmation and never performs delivery. Rule-driven document requests
receive a linked correspondence record and may update requirement status only
through this approved transition.

Inbound and internal items are manual records. Sensitivity headings are stored
prominently but do not constitute an automated privilege or legal determination.

## Consequences

- The platform preserves review accountability and prevents the older document
  request endpoint from bypassing approval.
- Approved/sent wording is immutable and auditable.
- Users still dispatch through an external system and record the result.
- Email sending, mailbox ingestion and synchronization remain outside this ADR.
