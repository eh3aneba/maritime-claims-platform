# Phase 17.6-P — Bounded SFTP generation-3 successor restaging

Phase 17.6-P consumes one exact completed Phase 17.6-O observation only when its result is `changed`.

## Operator input
An organization Admin with MFA supplies only:
- `request_key`
- `reason`

Host, port, username, credential reference, remote path, generation, content, digest, storage key and object-store coordinates are derived internally from verified lineage and cannot be supplied by the caller.

## Execution
P performs one bounded reread of the exact lineage-derived SFTP file and:
1. checks the reread against O’s observed byte size;
2. enforces the 8 MiB ceiling;
3. creates a SHA-256/byte-count content proof;
4. commits that proof before object-storage PUT;
5. stages one deterministic generation-3 object with put-if-absent;
6. verifies the object by digest and size;
7. records immutable receipts.

A reread equal to the current generation-2 checkpoint digest is rejected because no new content version exists.

## Recovery
If execution stops after the content proof is durable:
- an already-present valid generation-3 object is reconciled and completion proceeds without rereading SFTP;
- if the object is absent, the exact file may be reread once and must match the committed proof before PUT.

Exact replay is idempotent. A distinct second consumption of the same O changed observation conflicts.

## Explicitly not granted
No directory listing, provider mutation, storage overwrite/delete/copy, checkpoint advancement, Document/Evidence creation, processing/OCR/indexing, AI, Claim mutation, or recurring/background sync is authorized.

The next bounded phase may advance an immutable generation-3 checkpoint from the completed P candidate using persisted control-plane facts only.
