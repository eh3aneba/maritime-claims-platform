# Sprint 9 — Policy, Contract and Claims Control

## Phase A — Human-reviewed Policy & Contract Intelligence

Goal: convert policy and contract wording into a source-linked reviewed term
register and explainable issue spots without automating coverage.

Delivered scope:

- Deterministic local extraction from secured document text with no external AI.
- Candidate taxonomy for period, value/limits, deductible, notice, time limits,
  law/jurisdiction, clauses, exclusions, warranties and marine-specific wording.
- Exact source quote, locator, confidence, document family/version and review warnings.
- Existing field-level Approve/Edit/Reject and append-only audit history.
- Permanent separation between Policy Terms and casualty Claim Facts.
- Tenant-scoped reviewed term register and source-version state.
- Explainable issue spots with explicit human action.
- Policy Intelligence claim workspace and MT ORION browser coverage.
- Inclusion in newly generated immutable claim-pack snapshots.

Acceptance guardrails:

- no automatic covered/not-covered conclusion
- no automatic application of exclusions, warranties, deductibles or time bars
- no automatic causation, liability, fraud, recoverability, reserve or settlement determination
- no pending candidate becomes authoritative
- policy replacement never transfers approval
- no external AI receives evidence

## Phase B — Controlled Correspondence Centre

Delivered scope:

- Claim-linked outbound drafts plus manually filed inbound/internal records.
- Manager/Admin review gate before external-dispatch recording.
- Immutable approved content hash and append-only audit trail.
- Standard, Confidential, Privileged & Confidential and Without Prejudice labels.
- Existing document requirements and follow-up tasks reused without a parallel workflow.
- Explicit dispatch confirmation; the platform does not send email.
- Tenant-scoped API and claim-level Correspondence Centre workspace.

Acceptance guardrails:

- no email sending, mailbox reading or synchronization
- no approval by Claims Handlers
- no Sent Externally state before approval and explicit confirmation
- no editing approved or sent content
- no automatic legal-effect, coverage, causation, liability or settlement determination

## Phase C — Advanced Financial Adjustment Controls

Delivered scope:

- Currency-specific versioned adjustment statements from reviewed invoice lines.
- Frozen Cost Item, Document and AI Run source snapshots.
- Explicit human treatment: included, excluded, apportioned or credit.
- Explicit human basis: PA, GA, Sue & Labour, RDC, other or not applicable.
- Written reasons for exclusions, apportionments, credits and amount differences.
- Human-entered deductible and other deduction/credit with written basis.
- Deterministic gross, considered and adjusted arithmetic with no FX conversion.
- Draft → Manager/Admin review → immutable approved version.
- Reserve comparison without automatic reserve changes.
- Claim-level Adjustment Workspace, tenant controls and audit history.

Acceptance guardrails:

- no automatic coverage, recoverability, betterment, maintenance or depreciation decision
- no quotation double counting
- no FX conversion
- no automatic reserve update
- no settlement offer, payment instruction or payment authorization
- no editing approved versions

## Next phases

## Phase D — Controlled Settlement & Payment Ledger

Delivered scope:

- Versioned settlement proposals sourced only from approved immutable adjustment statements.
- Same-currency proposal cap at the approved adjusted total with no FX conversion.
- Draft → Manager/Admin review → immutable approved proposal.
- Explicit manual accepted, declined or withdrawn outcome recording.
- Payment authorizations linked only to accepted settlements.
- Two distinct Manager/Admin approvals; creator cannot approve.
- Immutable authorization SHA-256 snapshot after the second approval.
- Explicit paid-externally recording with channel, external reference and value date.
- Cumulative authorization cap, tenant isolation and append-only audit history.

Acceptance guardrails:

- no automated settlement recommendation, acceptance or coverage decision
- no offer sending or mailbox integration
- no bank integration, payment instruction or money movement
- no single-person payment authorization
- no FX conversion or automatic reserve change
- no paid state without explicit confirmation and external execution reference
- no editing of approved proposals or fully authorized payment content

## Next phase

## Phase E — Controlled Email Intake

Delivered scope:

- Provider-neutral normalized webhook; no provider OAuth token storage.
- Manager/Admin connection setup with explicit consent basis and 1–365 day retention.
- One-time ingestion token stored only as SHA-256.
- Active, suspended and irrevocably revoked connection lifecycle.
- Provider-message deduplication, bounded payloads and immutable content hashes.
- Deterministic claim-reference suggestion without automatic linking.
- Human link/reject decision with written reason and explicit confirmation.
- Linked email becomes inbound Correspondence Centre content.
- Attachment metadata remains blocked pending the existing quarantine and malware path.
- Audited retention expiry redacts staged message content.

Acceptance guardrails:

- no mailbox-wide synchronization or Gmail/Outlook OAuth in this phase
- no email sending, reply or forwarding
- no plaintext ingestion-token or provider access-token storage
- no automatic claim link, fact promotion or attachment evidence admission
- no ingestion after suspension, revocation or consent withdrawal
- no external AI processing
- no indefinite staging retention

## Next phase

Operational pilot hardening for controlled email provider adapters and retention scheduling.

## Phase F — Email Provider Adapter Operations

Delivered scope:

- adapter registration only against an active consented connection
- provider kind, allowlisted folder, deployment secret reference and canonical least-privilege permissions
- bounded batch size, idempotent run ledger and one-way checkpoint hashes
- suspended/revoked lifecycle and connection-state enforcement
- idempotent tenant-scoped retention-run ledger
- no stored OAuth access/refresh token and no send/write/delete capability

## Phase G — External Collaboration Portal

Delivered scope:

- named, purpose-bound and claim-scoped invitation with 1–168 hour expiry
- one-time invitation token and expiring session token stored only as SHA-256
- explicit permission and published-item allowlists
- claim summary without reserve, adjustment, settlement, audit or AI material
- staged external messages and attachment manifests with human promote/reject review
- promotion creates inbound Portal correspondence; attachment bytes remain blocked
- replay, revocation, expiry and tenant-isolation enforcement

## Phase H — Deployment Readiness Gates

Delivered scope:

- versioned staging/pilot readiness snapshots across eight explicit controls
- deterministic snapshot hashing and immutable attestation record
- all-controls-pass rule before readiness; Manager/Admin attestation only
- evidence of readiness rather than a production-certification claim

## Phase I — Operational Monitoring & Incident Response

Delivered scope:

- idempotent tenant-scoped monitoring runs with count-only metrics
- deterministic thresholds for adapter failures, intake backlog and expired portal sessions
- human-owned incident ledger with acknowledge and resolve transitions
- no email body, evidence text, portal message or secret in telemetry

## Phase J — Four-eyes External Publication

Delivered scope:

- direct publication at invitation creation disabled
- eligible correspondence/document-metadata proposal queue
- proposer/reviewer separation and Manager/Admin review
- privileged correspondence, restricted evidence and unreviewed sources blocked

## Phase K — Pilot Data Governance & Exit Controls

Delivered scope:

- approved purpose, legal basis, owner, retention, residency and exit contact profile
- claim-scoped, idempotent exit manifests containing counts rather than record content
- SHA-256 manifest checksum and explicit authorization record
- manifest generation performs no deletion and makes no regulatory-compliance claim

## Next phase

Design-partner rehearsal, evidence collection against the readiness controls, and remediation of findings before any production-go-live decision.
