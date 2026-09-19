# ADR-231: Canonical N+1 admission for bound external Evidence families

## Status

Proposed by Phase 17.5-AA.

## Context

Phase X admitted one exact human-authorized external source version as canonical Evidence.
Phase Y bound that initial Document to a durable provider-agnostic source-item / Document-family anchor.
Phase Z added an exact-version processing-release boundary.

A later remote source version must become canonical Evidence without overwriting history, mutating the
immutable Y binding receipt, inheriting processing authority, or creating another generation-specific
integration schema.

## Decision

Reuse the existing trusted S → T → U → V → W pipeline for every later candidate:

1. S proves the exact source item changed.
2. T rereads and durably stages the changed bytes.
3. U records the generation-3 checkpoint.
4. V confirms the staged candidate is still the exact current remote version.
5. W records a new human Evidence-admission authorization for that exact candidate.
6. AA consumes that authorization and admits one canonical N+1 Document version into the already-bound family.

The Y row remains an immutable family anchor and v1 provenance snapshot. Its historical fields named
`current_document_id` / `current_version_number` are not rewritten by AA. Canonical current-version truth
comes from the Documents family invariant: exactly one non-deleted `Document.is_current = true` per
organization / Claim / `document_family_id`.

AA row-locks the durable Y family binding and the canonical current Document before transition. The prior
Document is preserved as immutable historical Evidence except for canonical supersession fields. The new
Document receives the same family ID, deterministic version N+1 and `supersedes_document_id = vN.id`.

A W authorization is single-use across both X and AA. X and AA both lock the same authorization row before
consumption, preventing cross-path double admission.

A prior Phase-Z release never follows the family automatically. Processing authority is resolved against
the exact canonical current Document. Once vN+1 is current, a release for vN is non-executable and vN+1
requires its own release.

## Failure and concurrency rules

- Remote currentness is revalidated immediately before canonical admission.
- Staged content hash, byte count, file signature and fresh authoritative malware status are rechecked.
- Same-content duplicates fail closed.
- An authorization older than the current canonical Document is stale and cannot become an unintended N+2.
- PostgreSQL row locks and family/version uniqueness prevent two concurrent N+1 admissions from producing
  two current Documents.
- DB/storage failure rolls back supersession and removes uncommitted canonical/quarantine bytes.

## Non-authority

AA does not authorize or enqueue OCR, text extraction, indexing, AI, ClaimFact/assessment mutation,
checkpoint advancement, recurring synchronization or background polling.
