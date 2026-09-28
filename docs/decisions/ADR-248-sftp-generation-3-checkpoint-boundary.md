# ADR-248: Advance SFTP generation-3 checkpoint custody without external I/O

## Status
Accepted for Phase 17.6-Q.

## Context
Phase 17.6-P produces one immutable generation-3 SFTP quarantine candidate from one exact Phase 17.6-O changed observation. The candidate is already content-proved and storage-verified. Advancing checkpoint custody is a distinct control-plane authority increment and does not require another provider or object-store observation.

## Decision
Phase 17.6-Q:
- consumes one exact completed integrity-valid P generation-3 candidate;
- requires the exact Phase 17.6-N generation-2 checkpoint bound through P;
- verifies generation continuity 2 → 3;
- revalidates persisted lineage and immutable hashes fail-closed;
- derives one deterministic generation-3 checkpoint state hash;
- persists one immutable requested/completed advancement receipt chain.

Q performs no SFTP or object-store I/O. It calls P integrity verification with storage verification disabled because the candidate's already persisted completion proof is the authority boundary for this phase.

## Stored and exposed facts
Q may expose only bounded/hash-safe custody facts:
- provider/profile identity hashes;
- predecessor checkpoint generation/state/completion hashes;
- P scope/request/content-proof/completion hashes;
- O scope/completion hashes;
- candidate generation, content SHA-256 and byte count;
- sanitized storage backend/purpose and object-key hash;
- generation-3 checkpoint kind/generation/state hash;
- request/scope/completion and receipt hashes.

Raw storage key, ETag, hostname, remote path, credentials, sessions and file body remain internal or excluded.

## Concurrency
The P candidate and generation-2 predecessor checkpoint are row-locked. Database uniqueness guarantees:
- one Q advancement per P candidate;
- one generation-3 successor per generation-2 predecessor within this bounded path;
- idempotent exact replay;
- conflict for changed replay or competing second advancement.

## Consequences
Checkpoint advancement remains independently reviewable from content reread/restaging and future metadata observation. A later phase may perform a fresh exact-file metadata observation against the generation-3 checkpoint.
