# ADR-249: SFTP generation-3 exact-file observation boundary

## Status

Accepted for Phase 17.6-R implementation.

## Context

Phase Q advances one verified Phase P generation-3 candidate into an immutable generation-3 checkpoint. The next safe authority increment is a fresh observation of the same exact remote file without reading file content or touching object storage.

## Decision

Phase R performs one manually triggered, Admin+MFA, exact-item SFTP metadata/stat operation against one exact completed Q checkpoint.

The trusted comparison baseline is reconstructed from Q/P/O persisted lineage. Q/P content byte count and P/O modified-time and metadata identity define the generation-3 metadata projection. Older listing/credential lineage is used only to recover the same governed remote locator and connection authority.

The execution may classify only:
- `unchanged`;
- `changed`;
- canonical `missing`.

Only the existing canonical remote-not-found adapter result maps to `missing`. Other provider failures fail closed.

## Authority boundary

Allowed:
- transient credential resolution;
- pinned-host-key SSH/SFTP connection;
- one exact-file metadata/stat operation;
- deterministic comparison and immutable receipts.

Forbidden:
- directory listing;
- remote content read;
- provider mutation;
- object-store I/O;
- restaging or checkpoint mutation;
- Evidence/Document creation;
- processing/OCR/indexing/AI;
- Claim mutation;
- recurring synchronization.

## Replay and integrity

Exact replay is idempotent and performs no second provider call. Changed replay conflicts. Every read revalidates the complete Q/P/O and deeper persisted lineage. Q and P remain immutable.

## Consequence

R proves current exact-file metadata only. It creates no Evidence authority. A later independently reviewed phase may authorize one latest integrity-valid R `unchanged` observation for initial SFTP Evidence admission.
