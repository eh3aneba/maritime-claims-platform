# Phase 17.5-X — Consume authorization and admit one external Evidence item

Phase X is the first execution boundary that may turn governed external-source bytes into a local Claim `Document`.

An Admin with MFA may execute one previously recorded Phase-W authorization. The same actor must execute the admission. The authorization remains immutable; consumption is represented by a separate unique execution row and receipt.

## Admission sequence

Before a Document is created, the service verifies all of the following:

- the authorization and authorization receipt are intact;
- the Claim remains active and tenant-scoped;
- no newer completed generation-3 observation exists for the authorized checkpoint;
- one fresh exact-item provider metadata read still matches the authorized projection exactly;
- the Phase-T generation-3 staged object still matches its persisted SHA-256, byte-count and storage proof;
- the staged bytes match the authorized remote size where the provider supplied a size;
- filename/type is supported and the local Evidence copy passes signature validation;
- authoritative admission-time malware scanning returns clean;
- the same bytes do not already exist in the Claim Evidence record.

Only after those checks are the bytes promoted into canonical Document storage and one Document, admission execution, receipt and audit event committed.

## Explicit non-authority

Phase X does not reread provider file content. It does not list folders, mutate or delete provider data, modify the staged object, advance checkpoints, create subscriptions, or start recurring synchronization.

The admitted Document remains in `uploaded` processing state. No OCR, parsing, extraction, indexing, AI analysis, chronology update, financial update, Claim assessment mutation or other downstream processing is enqueued by Phase X.

## Replay and failure behavior

An exact replay of an already completed admission returns the existing execution without repeating provider metadata, staged-storage or malware work. A changed replay conflicts. A second execution for the same authorization is prevented by a unique database constraint and authorization-row lock.

Stale authorization, remote metadata drift, missing staged bytes, integrity mismatch, unsupported/signature-invalid bytes, malware detection, scanner failure, cross-tenant access, actor mismatch, deleted Claim, duplicate Evidence bytes or persistence failure all fail closed.

If canonical local storage promotion succeeds but the database commit fails, the newly written canonical object is deleted so an untracked active Evidence object is not left behind.

## Operator note

Phase-W authorization and Phase-X admission are distinct human-control events. If a newer generation-3 observation exists, do not bypass the stale-authorization failure: review the new remote version and create a new authorization before admitting it.