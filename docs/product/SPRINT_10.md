# Sprint 10 — Private Pilot Evidence and Production Baseline

## Phase A — Private Pilot Execution & Product-Gap Baseline

Goal: turn a successful design-partner rehearsal into a bounded, measurable and human-controlled private pilot without treating pilot activity as proof of production readiness.

Delivered scope:

- one tenant-scoped pilot execution per completed Go rehearsal
- synthetic mode by default; approved-real mode requires approved governance and an allowlisted authorization reference
- explicit Manager/Admin start and completion gates
- claim-linked case runs with workflow durations, AI-review decisions, rule usefulness and open-work counts
- aggregate outcome metrics that exclude narrative, evidence text and personal data
- P0–P3 product-gap ledger with category, owner, due date, bounded evidence reference and explicit transition
- deterministic Proceed block while any P0 gap remains unresolved
- immutable canonical SHA-256 Proceed/Pause/Stop outcome and append-only audit events

Acceptance guardrails:

- no pilot can start without a completed Go rehearsal
- no case run can be recorded before a Manager/Admin starts the execution
- no approved-real execution without approved governance and bounded authorization evidence
- no automatic AI or rule acceptance, product-gap closure or pilot outcome
- no claim content, evidence content, secret or credential in aggregate metrics
- no production, regulatory or compliance certification
- no editing after the pilot outcome is frozen

## Phase B — Production Architecture Baseline

Goal: convert pilot evidence into an accountable view of the current and target production architecture while keeping every residual gap visible.

Delivered scope:

- baseline anchored to a completed private-pilot execution
- deployment model and residency-region declaration
- exactly nine required domains: identity/access, application security, evidence storage, observability, backup/DR, data governance, deployment/IaC, interoperability and AI governance
- per-domain current state, target architecture, residual risk, owner, target date and bounded evidence reference
- draft-to-review-ready completeness state
- Manager/Admin-only attestation with an immutable canonical SHA-256 snapshot
- `attested_with_gaps` outcome whenever any domain is missing or partial
- explicit `production_certification: false` in every summary

Acceptance guardrails:

- no architecture baseline before a completed pilot
- no attestation until all nine domains are documented
- no automatic promotion of a missing or partial control
- no deployment, infrastructure mutation, compliance claim or go-live authorization
- no editing after attestation

## Phase C — Production Control Evidence & Independent Verification

Goal: move five foundational architecture domains from stated targets to retained implementation evidence and reproducible human verification without claiming deployment, certification or go-live authority.

Delivered scope:

- one tenant-scoped verification gate per attested architecture baseline
- exact foundational set: identity/access, secure evidence storage, observability, backup/DR and deployment/IaC
- versioned append-only submissions containing implementation summary, verification method, rollback plan, owner, completion time and bounded evidence reference
- a different Manager/Admin must verify or reject each submission
- rejected submissions remain visible and only a new version can replace the current attempt
- deterministic completion block until the latest version of all five controls is independently verified
- immutable canonical SHA-256 completion snapshot and audit trail
- explicit `production_certification: false`, `go_live_authorization: false` and `content_or_secrets_included: false`

Acceptance guardrails:

- no gate before architecture attestation
- no self-verification and no automatic conclusion
- no URL, secret, credential, raw artifact or claim content storage; only bounded allowlisted references
- no mutation of verified evidence or completed snapshots
- no deployment action, cloud-provider mutation, compliance claim or production go-live authorization

## Phase D — Complete Production Control Verification

Goal: extend the evidence and independent-review contract to every domain in the attested production architecture while preserving completed five-control snapshots as truthful historical records.

Delivered scope:

- new `architecture_v2` gates require identity/access, application security, evidence storage, observability, backup/DR, data governance, deployment/IaC, interoperability and AI governance
- application security, data governance, interoperability and AI governance use the same versioned submission, rejection/resubmission and four-eyes review lifecycle
- each gate carries an immutable verification profile; existing `foundational_v1` gates retain their original five-control scope
- deterministic completion block until the latest version of all controls in the gate profile is independently verified
- adaptive UI reports the profile, required count and exact control set instead of assuming a fixed scope
- canonical v2 SHA-256 snapshot includes the nine-control profile and preserves the explicit false certification/go-live flags

Acceptance guardrails:

- no retroactive expansion or re-hashing of a completed Sprint 10C snapshot
- no control may be submitted outside the gate's immutable profile
- no weakening of independent review, bounded-reference, tenant, role or append-only constraints
- no infrastructure mutation, production certification, compliance conclusion or traffic enablement

## Next phase

Perform a separately authorized operational acceptance and go-live decision with named approvers, change-window and rollback ownership, while keeping verification evidence distinct from authorization to enable production traffic.
