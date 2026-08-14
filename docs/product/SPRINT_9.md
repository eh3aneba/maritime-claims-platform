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

1. Controlled settlement and payment authorization ledger.
2. Email ingestion only after provider, consent and retention controls are designed.
