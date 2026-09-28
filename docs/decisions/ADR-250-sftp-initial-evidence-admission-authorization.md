# ADR-250: Human-controlled initial SFTP Evidence admission authorization

## Status

Accepted for Phase 17.6-S implementation.

## Context

Phase R can establish that one exact SFTP file still matches the immutable generation-3 baseline. That observation alone must not create Evidence authority.

The next boundary must record explicit human intent for one Claim while preserving the existing no-implicit-admission rule.

## Decision

Phase S records one immutable Admin+MFA authorization binding:
- one active tenant Claim;
- one latest integrity-valid Phase R `unchanged` observation;
- the exact Q generation-3 checkpoint;
- the exact P generation-3 staged candidate.

The authorization binds only internal identifiers and safe hashes/metadata, including the exact content SHA-256 and storage object key hash. It never exposes or stores a raw storage key, remote path, credential, session material, token or file body.

The exact Q checkpoint row is locked before the latest-observation decision. This serializes authorization with any concurrent Phase R execution, because R itself locks that same checkpoint while creating a new observation.

## Authority boundary

Phase S performs no:
- credential resolution;
- provider/SFTP network;
- stat/list/read/write;
- object-storage I/O;
- restaging/checkpoint mutation;
- Document/Evidence creation;
- OCR/parsing/indexing/extraction;
- processing/AI;
- Claim mutation;
- recurring synchronization.

## Currentness and replay

New authorization requires the referenced R observation to be the latest completed observation for its Q checkpoint and to remain exactly `unchanged`.

Historical authorizations remain immutable and integrity-verifiable even if later observations appear. A future admission execution must independently revalidate currentness before consuming the capability.

Exact replay is idempotent. Changed replay conflicts.

## Consequence

Phase T can consume a narrowly scoped human capability for exactly one governed SFTP object version instead of receiving general provider or storage authority.
