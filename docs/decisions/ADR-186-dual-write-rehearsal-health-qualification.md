# ADR-186: Independent health qualification for one completed dual-write rehearsal

## Status

Proposed for Phase 17.3-Z.

## Context

Phase X authorizes one tightly bounded recovery-storage write rehearsal. Phase Y consumes that authorization and writes one isolated, deterministic, create-only rehearsal object, then verifies the object with HEAD + GET + SHA-256 while preserving the local document as the only authoritative/routed evidence source.

A successful Phase Y execution is not itself authority to enable live dual-write, change the write path, or migrate storage ownership. Before any stronger write capability can be considered, MCRI needs an independent qualification artifact proving that the completed rehearsal remains healthy after execution and that the local authority boundary has not drifted.

## Decision

Phase Z creates a non-routable health qualification for exactly one completed Phase Y execution.

A Phase Z request is admitted only when all of the following can be freshly proven:

- exactly one completed Phase Y execution and immutable execution receipt exist;
- Y remains bound to the exact Phase X approval and the W → V → U → T → replica lineage;
- Y executed while the Phase X authorization was valid;
- all Phase X and Phase Y no-cutover/no-destruction safety flags remain intact;
- the shared route is still exact clean local authority at the same route version preserved by Y;
- the authoritative local document still matches the Y source hash, size, and storage-key fingerprint;
- the recovery replica lineage still matches the Y execution;
- the deterministic isolated rehearsal key is independently re-derived and remains distinct from both local authoritative and recovery-replica keys;
- a fresh HEAD + GET of the rehearsal object reproduces the exact expected SHA-256 and byte length;
- the recovery bucket identity and object metadata remain consistent with Y.

The request records a hash-bound snapshot and a fresh integrity proof. A second Admin + MFA actor must independently qualify it within ten minutes. The qualifier must differ from the requester, the Phase Y executor, and the Phase X approver. Qualification performs the full fresh verification again. Storage unavailability is retryable; lineage, authority, key, or integrity drift invalidates the pending qualification.

## Safety boundary

Phase Z is evidence only. It does not:

- write a new storage object;
- create routable dual-write authority;
- make the rehearsal object routable or authoritative;
- activate live or durable dual-write;
- switch the read path or write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- overwrite, copy, move, or delete authoritative evidence;
- issue S3 COPY, DELETE, or lifecycle mutations;
- grant disposal authority.

The isolated Phase Y rehearsal object remains non-routable and non-authoritative. Physical deletion remains outside this phase.

## Consequences

A later phase may consume only an explicitly `qualified` Phase Z artifact as evidence when requesting stronger write capability. Phase Z itself grants no such capability. Any future live dual-write, write routing, storage ownership migration, permanent cutover, or destructive operation requires a separate authorization and execution boundary.
