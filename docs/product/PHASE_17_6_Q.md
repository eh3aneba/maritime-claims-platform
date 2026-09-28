# Phase 17.6-Q — SFTP generation-3 checkpoint advancement

Phase 17.6-Q advances control-plane checkpoint custody from an exact completed Phase 17.6-N generation-2 checkpoint to one exact integrity-valid Phase 17.6-P generation-3 quarantine candidate.

## Operator input
An organization Admin with MFA supplies only:
- `request_key`
- `reason`

All generation, lineage, digest, byte-count and storage custody facts are derived from persisted P/N lineage. Caller-supplied path, connection, content, credential, digest, generation or storage fields are rejected.

## Execution
Q:
1. locks and verifies the exact P candidate;
2. locks and verifies the exact N predecessor checkpoint;
3. requires generation continuity 2 → 3;
4. verifies P candidate content/custody hashes against N predecessor lineage;
5. derives a deterministic generation-3 checkpoint state hash;
6. persists requested/completed receipts.

## Zero-I/O boundary
Q performs no:
- credential resolution;
- SSH/SFTP connection;
- stat/list/read/write or remote mutation;
- object-store PUT/HEAD/GET/delete/copy/reconciliation;
- content observation/restaging;
- Document/Evidence creation;
- processing/OCR/indexing;
- AI execution;
- Claim mutation;
- recurring/background sync.

Exact replay returns the same advancement without external I/O. A changed replay or competing second successor conflicts.
