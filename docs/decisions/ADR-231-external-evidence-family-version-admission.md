# ADR-231: Canonical N+1 admission for bound external Evidence families

## Status

Proposed by Phase 17.5-AA.

## Context

Phase X admitted one exact human-authorized external source version as canonical Evidence.
Phase Y bound that initial Document to a durable provider-agnostic source-item / Document-family anchor.
Phase Z added an exact-version processing-release boundary.

A later remote source version must become canonical Evidence without overwriting history, mutating the
immutable Y binding receipt, inheriting processing authority, or creating an unbounded chain of generation-specific
checkpoint tables.

The existing external-source lineage has an important structural invariant: Phase U permits only one
generation-3 successor checkpoint for a Phase-R predecessor. Therefore a later N+1 candidate must not attempt
to repeat U/V/W against the same R checkpoint.

## Decision

Use the repeatable part of the existing trusted lineage for every later candidate:

1. **S** performs a fresh exact-item metadata observation from the durable Phase-R baseline and proves a change.
2. **T** rereads and durably stages the exact changed bytes with content proof.
3. **AA authorization** records a separate human authorization bound to that exact Phase-T candidate, the Y family,
   and the exact canonical current Document/version expected to be superseded.
4. **AA execution** performs one fresh exact-item metadata read immediately before canonical mutation and requires
   it to match the authorized candidate exactly.
5. AA rereads the governed staged object, verifies SHA-256/byte count, validates file signature, obtains a fresh
   authoritative malware verdict, and creates canonical Document N+1.

No Phase-U checkpoint advancement is performed for N+1 admission. This preserves U's one-successor invariant
while avoiding generation-4 tables.

The Y row remains an immutable family anchor and v1 provenance snapshot. Its historical fields named
`current_document_id` / `current_version_number` are not rewritten by AA. Canonical current-version truth
comes from the Documents family invariant: exactly one non-deleted `Document.is_current = true` per
organization / Claim / `document_family_id`.

AA authorization and AA execution are separate immutable decisions with separate receipts. Authorization performs
no remote read, storage read/write, Document mutation, processing enqueue or AI execution. Execution consumes the
authorization exactly once.

The prior Document is preserved as immutable historical Evidence except for canonical supersession fields. The new
Document receives the same family ID, deterministic version N+1 and `supersedes_document_id = vN.id`.

A prior Phase-Z release never follows the family automatically. Processing authority is resolved against the exact
canonical current Document. Once vN+1 is current, a release for vN is non-executable and vN+1 requires its own release.

## Failure and concurrency rules

- The Phase-T candidate must be the latest completed Phase-S observation for its Phase-R source baseline when
  human authorization is recorded.
- Authorization snapshots the exact current canonical Document ID/version/file hash.
- Execution fails closed if the current Document changed after authorization.
- Remote currentness is revalidated immediately before canonical admission.
- Staged content hash, byte count, file signature and fresh authoritative malware status are rechecked.
- Same-content duplicates fail closed.
- PostgreSQL row locks and family/version uniqueness prevent two concurrent N+1 admissions from producing
  two current Documents.
- DB/storage failure rolls back supersession and removes uncommitted canonical/quarantine bytes.
- Exact execution replay returns the committed result without repeated remote/storage mutation.

## Processing guard compatibility

Phase-X admitted Evidence remains protected before Phase Y exists. After Y exists, every Document in that bound
family—including later AA versions—is protected by the Phase-Z processing-release guard.

## Non-authority

AA does not authorize or enqueue OCR, text extraction, indexing, AI, ClaimFact/assessment mutation,
checkpoint advancement, recurring synchronization or background polling.
