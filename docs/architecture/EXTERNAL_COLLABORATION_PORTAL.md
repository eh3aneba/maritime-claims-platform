# Claim-scoped External Collaboration Portal

The portal is a separate external trust boundary, not an internal user role. A Manager/Admin issues a named, purpose-bound invitation for one claim, 1–168 hours, an explicit permission manifest and optional reviewed items. The invitation token is displayed once and stored only as SHA-256. Acceptance is one-time and returns a separately hashed session lasting no more than 12 hours or the remaining invitation life.

The external projection contains only claim reference, vessel name, incident date/description, manually published item titles/summaries and that participant's submissions. It excludes reserves, financial adjustment, settlement/payment, audit logs, AI runs, internal notes, privileged correspondence and raw evidence downloads.

External messages enter `pending_review`. Attachment metadata is recorded as `blocked_pending_quarantine`; bytes are not accepted. An internal user must promote or reject with a reason. Promotion creates inbound Portal correspondence and does not promote attachment manifests into evidence.

Revocation invalidates every session immediately. Expired invitations/sessions return no portal data. All creation, acceptance, submission, promotion, rejection and revocation events are audited.
