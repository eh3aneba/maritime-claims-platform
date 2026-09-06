# ADR-111 — Document-request context binding and governed Claim Pack correspondence

## Status
Accepted for Phase 13.9B.

## Context
Phase 13.9A gave material correspondence content a deterministic fingerprint/version, moved human approve/reject decisions into append-only review lineage, and bound an external-dispatch record to the exact human approval and approved content hash.

Document-request correspondence still has a second kind of state that can evolve without changing the wording itself: the linked request batch and document requirements. A requirement may be received, rejected, satisfied or otherwise evolve after wording was reviewed. Treating those changes as ordinary communication edits would incorrectly stale unrelated free-form correspondence; ignoring them would allow a request-linked dispatch to rely on a human approval of an earlier request context.

Claim Pack also lacked governed correspondence history. Adding it must not create a parallel communication authority, imply that the platform sent a message, or silently export material marked `PRIVILEGED & CONFIDENTIAL` or `WITHOUT PREJUDICE`.

## Decision

### 1. Communication identity and dynamic request-context identity remain separate
The Phase 13.9A `state_fingerprint` / `state_version` continues to identify the material communication content and static linkage reviewed by the operator.

Request-linked correspondence additionally receives a server-computed `request_context_fingerprint` at human review time. The context fingerprint covers material state of the linked document-request batch and linked requirements, including the request wording/context, requirement identity, rule provenance, status, satisfaction state and evidence linkage.

Volatile timestamps and unrelated claim activity are excluded. Free-form correspondence has no request-context fingerprint.

This separation prevents an unrelated document-requirement change from invalidating an ordinary status update while still protecting document-request dispatch from stale request context.

### 2. Request context is computed and locked server-side
Clients do not supply or choose the request-context fingerprint. The service resolves the linked batch/requirements in the same tenant and claim scope and computes the deterministic fingerprint itself. Review and dispatch transitions lock the relevant rows where the context must be stable for the transition.

Missing linked request or requirement state fails closed for new governed actions rather than silently weakening the binding.

### 3. Human review lineage binds to both identities
Each new `correspondence_review_decisions` row may carry `request_context_fingerprint` in addition to the exact correspondence fingerprint/version and content hash.

For request-linked correspondence, the review hash includes the request-context fingerprint. The resulting lineage therefore proves which communication state and which request context the human approved or rejected.

Migration 0077 deliberately leaves existing request-context fingerprint values null. Historical Phase 13.9A reviews cannot truthfully be backfilled with a dynamic context that was not persisted at the time of review.

### 4. Context evolution requires deliberate re-review before dispatch
If an approved but unsent request-linked correspondence no longer matches the latest reviewed request context:
- its communication `state_fingerprint` / `state_version` remains unchanged;
- the review is reported as stale, or legacy-unbound for pre-13.9B review lineage;
- external-dispatch recording fails closed with HTTP 409; and
- the operator must deliberately resubmit the unchanged wording for request-context review and append a new human review using explicit re-review confirmation.

The earlier review remains immutable historical lineage.

### 5. Recorded external dispatch remains historical and immutable
Once a user has explicitly confirmed `Sent Externally`, the record remains bound to its stored `sent_review_hash` and approved content hash. Later request/requirement evolution does not retroactively make the historical dispatch record stale or rewrite the review that authorized it.

Exact replay of the same recorded dispatch remains idempotent. A different replay remains a conflict.

The platform still does **not** send email, letters, portal messages or any other external communication. It only records a dispatch that a human confirms occurred outside the platform.

### 6. Claim Pack receives a bounded downstream correspondence projection
Claim Pack snapshot schema advances to `1.4` and includes `correspondence_history` as reporting context only.

Only correspondence already recorded as historical communication is eligible:
- `sent_externally`;
- `received_external`; and
- `filed_internal`.

Draft, under-review, approved-but-unsent, rejected and cancelled items are not projected as communication history.

The projection is bounded to the latest 50 eligible records, then presented chronologically. Body content is bounded to a 4,000-character excerpt per included record. Compact integrity metadata includes communication state/version, content hash, sent-review hash and latest human-review/request-context binding where available.

This is not a new communication ledger or authority. Canonical correspondence remains in the Correspondence module.

### 7. Privileged and without-prejudice material is excluded before snapshot creation
Correspondence marked:
- `privileged_confidential`; or
- `without_prejudice`

is excluded by default **before** item projection into the immutable Claim Pack snapshot. Subject, body, external reference, parties and integrity metadata for those excluded records are not copied into the snapshot. The snapshot carries only an aggregate count of sensitive records excluded under this policy.

There is no automatic override or silent inclusion path in Phase 13.9B.

These markings are handling/confidentiality signals only. The platform does not determine whether legal privilege or without-prejudice protection exists, and producing a Claim Pack does not determine or waive either protection.

### 8. PDF/XLSX renderers expose the same governed snapshot
PDF and XLSX outputs render only the already-filtered immutable `correspondence_history` snapshot. They display the downstream-reporting disclaimer, default sensitive-material exclusion notice, bounded-history counts and compact integrity metadata.

Renderers do not independently query correspondence or decide inclusion policy. This prevents format-specific divergence from the immutable snapshot.

## Authority and confidentiality boundary
This phase strengthens integrity and controlled reporting of human-authored/reviewed correspondence. It does not determine or recommend coverage, causation, liability, recoverability, governing law, time-bar legal effect, reserve adequacy, settlement, payment or claim closure.

Claim Pack remains a downstream review/reporting artifact. Correspondence remains human-authored/reviewed. The platform does not autonomously send communications. Privilege and without-prejudice labels remain human/legal handling signals, not machine legal conclusions.

## Consequences
- document-request dispatch fails closed when the actual linked request context has evolved after approval;
- human re-review records a new append-only lineage entry without inventing a new communication version;
- free-form correspondence is insulated from unrelated request-context churn;
- historical sent records remain auditable to the exact approval used at dispatch;
- Claim Pack gains bounded governed communication history without becoming a communication authority;
- privileged/without-prejudice content is not silently copied into immutable Claim Pack snapshots; and
- schema 1.4 records the new projection while preserving existing approved-assessment and Recovery/Time-Bar downstream reporting boundaries.
