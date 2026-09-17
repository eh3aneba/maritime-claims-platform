# ADR-228 — External Evidence admission execution

## Status
Accepted for Phase 17.5-X.

## Context
Phase 17.5-W records an immutable human authorization for one exact, unchanged generation-3 external-file observation and one Claim. That authorization intentionally has no authority to create a Document, read remote content, or start downstream processing.

The next boundary must turn one authorization into one local Evidence Document without weakening currentness, custody, tenant isolation, or the single-use human-control requirement.

## Decision
Phase X consumes one Phase-W authorization through a separate immutable admission execution. The Phase-W authorization row is never mutated to represent consumption; a unique admission execution keyed by `authorization_id` is the durable single-use fact.

Immediately before admission, Phase X:

1. locks and verifies the Phase-W authorization and its receipt;
2. requires the same human actor and an active same-tenant Claim;
3. rejects the authorization if any newer completed generation-3 observation exists for the checkpoint;
4. performs exactly one bounded exact-item metadata read and requires the remote projection to equal the authorized projection;
5. verifies and reads the already-governed generation-3 staged object rather than rereading remote file content;
6. copies those bytes into local Evidence quarantine, validates the allowed type and file signature, and performs a fresh authoritative malware scan;
7. promotes the clean bytes to canonical Document storage and creates exactly one `Document` plus one immutable admission execution/receipt;
8. commits the database mutation and audit record as one admission operation, cleaning up the canonical local object if commit fails.

## Authority boundary
Phase X may create exactly one local `Document`/Evidence record from one authorization. It may perform one exact remote metadata read, one staged-object HEAD/GET, and one canonical local Evidence write.

Phase X does **not** perform a remote content reread, folder/list operation, provider write/delete, staged-object write/delete, OCR, parsing, extraction, indexing, AI analysis, Claim assessment mutation, checkpoint advancement, subscription creation, or background synchronization. The new Document remains in `uploaded` processing state and no processing job is enqueued.

## Consequences
- Remote content authority remains narrower than a provider reread: bytes come from the immutable staged object already cryptographically bound into the generation-3 checkpoint.
- A newer observation invalidates an older human authorization even when the provider file later appears unchanged; a new authorization is required.
- Exact replay is idempotent and does not repeat provider/storage/scanner I/O. Altered replay fails closed.
- Existing `Document` claim/hash uniqueness continues to reject duplicate Evidence bytes.
- Later phases may separately authorize document-family/version semantics and downstream processing; neither is implied by this execution.