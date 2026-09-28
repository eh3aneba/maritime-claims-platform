# ADR-251: Consume SFTP authorization into one canonical initial Evidence Document

## Status

Accepted for Phase 17.6-T dependent implementation.

## Context

Phase S records immutable human intent for one exact current SFTP generation-3 file and one Claim. The authorization intentionally performs no provider/storage I/O and creates no Document.

The next boundary may create canonical Evidence, but it must not widen remote-content authority or start downstream processing.

## Decision

Phase T consumes one still-current Phase-S authorization exactly once.

Before admission T:

1. locks and integrity-verifies the S authorization;
2. requires the same human actor and active same-tenant Claim;
3. locks the exact Q generation-3 checkpoint through the S currentness helper;
4. rejects S if a newer completed R observation exists;
5. performs exactly one bounded exact-file SFTP metadata/stat read;
6. requires the fresh projection to equal the S-authorized projection;
7. performs no remote file-content read;
8. reads only the already-governed Phase-P generation-3 staged object;
9. verifies the staged object's SHA-256, byte count, ETag where available, storage-key hash and custody hashes;
10. copies the verified staged bytes into local Evidence quarantine;
11. validates file type and signature and obtains a fresh authoritative malware verdict;
12. promotes clean bytes to canonical Document storage;
13. creates exactly one initial Document/Evidence v1 plus one immutable execution and receipt.

The S authorization row remains immutable. Single-use is represented by a unique T execution keyed by authorization ID.

## Concurrency

T locks the S authorization row for single-use serialization. Currentness uses the same Q checkpoint row lock used by R/S, so a concurrent R observation cannot complete between the latest-observation decision and the T commit.

## Processing boundary

The new Document is immediately recognized by the existing processing guard as admitted external Evidence. Content-processing entrypoints therefore require a later explicit processing release. Security-only malware rescan remains separately governed by existing processing policy.

## Explicit non-authority

T performs no:
- SFTP remote content read;
- directory listing;
- provider mutation;
- staged-object write/delete;
- checkpoint/restaging mutation;
- OCR/parsing/indexing/extraction;
- processing enqueue;
- AI;
- Claim merits/assessment mutation;
- recurring synchronization.

## Failure and recovery

Exact replay returns the completed execution without repeating provider, staged-storage or malware work.

Stale authorization, fresh metadata drift/missing, staged-object absence/integrity drift, unsupported/signature-invalid bytes, malware detection/scanner failure, duplicate Evidence or persistence failure fail closed.

If canonical local promotion succeeds but the database transaction fails, the new canonical object is removed. If the database commit succeeds but response refresh fails, canonical Evidence remains and exact replay returns the committed execution.

## Consequence

T is the first SFTP phase that creates canonical Claim Evidence, while preserving the explicit separation between custody/admission and downstream processing authority.
