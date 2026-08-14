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

## Next phases

1. Email ingestion only after provider, consent and retention controls are designed.
2. Advanced financial adjustment controls.
