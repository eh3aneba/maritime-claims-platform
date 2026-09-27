# ADR-246: Keep generation-2 SFTP observation separate from checkpoint advancement

## Status
Accepted for Phase 17.6-O.

## Context
Phase 17.6-N creates one immutable generation-2 SFTP checkpoint from an exact integrity-valid Phase 17.6-M successor restaging candidate. The next authority increment needs to determine whether the same exact remote file still matches that generation-2 baseline.

Collapsing the fresh network observation into checkpoint advancement, reread/restaging, Evidence admission, or recurring synchronization would combine distinct trust boundaries and make replay, audit, and failure semantics harder to reason about.

## Decision
Phase 17.6-O is a separate Admin + MFA operation that:
- consumes one exact completed integrity-valid Phase 17.6-N checkpoint advancement;
- derives the comparison baseline from the Phase L observed metadata consumed by M/N, with byte size/content custody cross-checked against M/N;
- reuses the existing Phase L bounded exact-file SFTP metadata/stat adapter and policy;
- performs exactly one governed exact-file metadata/stat operation;
- persists only bounded/hash-safe observation and receipt facts;
- classifies the result as `unchanged`, `changed`, or canonical `missing`.

Only canonical remote not-found maps to `missing`. Other provider failures remain failures.

## Authority boundary
Phase 17.6-O does not:
- read or download remote file content;
- list directories;
- write, rename, delete, mkdir, chmod, chown, touch, or execute commands;
- read/write/reconcile/copy/delete object storage;
- stage/restage content;
- create or advance a checkpoint;
- create Document or admit Evidence;
- parse/OCR/index/extract;
- enqueue processing or execute AI;
- mutate Claims;
- create recurring/background synchronization.

## Baseline rule
The generation-2 comparison state is not the stale Phase 17.6-K metadata state. Phase 17.6-O uses:
- byte size from the exact M/N successor content custody;
- modified time and metadata-id hash from the exact Phase L observed projection consumed by M;
- the immutable N checkpoint state/completion hashes and M candidate proof/completion hashes.

K remains part of the verified path/connection lineage only.

## Consequences
Observation, reread/restaging, checkpoint advancement, and Evidence admission remain independently reviewable authority increments. A later phase may consume an O `changed` result for generation-3 reread/restaging.
