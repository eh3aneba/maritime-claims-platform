# Phase 17.5-AJ — Canonical admission of an authorized observation refresh

Phase AJ turns one exact Phase-AI-authorized AH refresh into the next immutable canonical Document version of an existing external Evidence family.

## End-to-end boundary

The recurring path becomes:

`schedule → due tick → service dispatch → metadata observation → review handoff → human decision → AH exact refresh/staging → AI admission authorization → AJ canonical N+1`

AJ is deliberately narrow. It consumes authority that already identifies one exact staged content version.

## Execution

AJ requires Admin + current MFA and accepts only:
- request_key;
- human execution reason.

The caller cannot provide a Document ID/version, storage key, content hash, malware verdict, provider identity, processing flag or AI authority.

Execution:
- locks and validates the exact AI authorization;
- verifies the AH refresh and durable family lineage;
- requires the AI-snapshotted prior Document to still be canonical current;
- reads only the governed AH staged object;
- verifies the staged object key hash, content SHA-256 and byte count;
- validates the file type/signature;
- obtains a fresh authoritative malware-clean verdict;
- writes one canonical local Evidence object;
- creates exactly one N+1 Document in the existing family;
- preserves vN as historical Evidence;
- records immutable execution and receipt hashes.

## Provider boundary

AJ performs no SharePoint or Google Drive I/O.

There is no token acquisition, provider-client construction, listing, metadata read or content read from the external provider in this phase.

This is important: an AI authorization is tied to the exact AH staged proof. AJ cannot silently follow a newer remote version.

## Storage and security

The raw AH staging object key is recovered only from trusted persisted AH lineage. The API never accepts or returns it.

AJ reads the staged bytes, then creates a separate local Evidence quarantine copy for signature and malware verification. A clean result is required before promotion to canonical storage.

Any security failure leaves the prior canonical Document current.

## Versioning

AJ reuses the Phase-AA canonical family transition rules:
- same document_family_id;
- deterministic version N+1;
- supersedes_document_id = vN;
- exactly one current non-deleted Document;
- vN remains historical and immutable.

Concurrent consumers serialize on the exact AI authorization and the canonical family/current Document boundary.

## Replay

Exact replay returns the already-committed AJ execution.

Replay does not:
- reread the staged object;
- rerun signature validation;
- rerun malware scanning;
- write storage again;
- create another Document.

An altered replay conflicts.

## Processing and AI

AJ enqueues no processing and runs no external AI.

Any processing release for vN becomes non-executable once vN+1 is current. The new version requires its own exact-version Phase-Z release.

AI governance remains separate from document-processing release and from AJ admission authority.

## Non-goals

AJ does not:
- poll or synchronize providers;
- advance recurring checkpoints;
- mutate Claim facts or assessments;
- infer coverage, liability, causation, settlement or fraud;
- parse/extract/index the admitted content;
- create processing or AI authority.

## Next

Phase 17.5-AK closes the live document integration loop end-to-end and verifies operator/provider wiring for SharePoint and Google Drive before the roadmap marks live document integration complete.
