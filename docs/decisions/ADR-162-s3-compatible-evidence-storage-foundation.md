# ADR-162 — S3-compatible evidence storage foundation before destructive disposal

## Status

Accepted for Phase 17.3-A implementation; production merge still requires the normal fresh explicit authorization.

## Context

Phase 17.2 established tenant retention policies, preservation signals, legal holds, governed disposal authorization, immutable execution manifests, dry-run attestation, reversible logical quarantine, and a final independent human release review. The final release review deliberately remains governance evidence only and creates no physical disposal authority.

The existing evidence admission path is local-filesystem based. It writes new uploads into an application quarantine key, performs file-signature and optional malware controls against a local path, and then promotes admitted bytes into their final evidence key. Its current cleanup/promotion semantics include local unlink/rename operations.

Mapping that workflow directly onto S3 would require decisions about quarantine-object copy/delete semantics, rollback, orphan cleanup, malware scanning/materialization, dual-read/cutover, and recovery. Introducing those decisions implicitly while also approaching irreversible disposal would create an unsafe coupling.

## Decision

Phase 17.3-A introduces an S3-compatible **foundation target**, not an active document-admission backend.

### 1. Active admission remains local

`STORAGE_BACKEND=local` remains the only supported active admission mode in this tranche. Selecting `STORAGE_BACKEND=s3` fails preflight with an explicit foundation-only error.

The local storage implementation is formalized behind `DocumentAdmissionStorage`, documenting the quarantine/promotion/cleanup capabilities the active workflow currently requires.

The S3-compatible foundation client intentionally does **not** implement that admission contract.

### 2. S3 foundation is separately configured and probed

`S3_FOUNDATION_ENABLED=true` enables validation and a signed, non-mutating `HEAD bucket` preflight probe while active evidence admission remains local.

Configuration includes:

- endpoint URL
- region
- bucket
- access key ID
- secret access key
- optional session token
- bounded request timeout
- bounded retry attempts
- TLS verification policy

Secret values use `SecretStr` in application settings and are never emitted through foundation health identity or storage error text.

Staging and production require HTTPS and TLS verification.

### 3. Foundation client operations are intentionally narrow

`S3CompatibleEvidenceStore` implements only:

- `PUT` object bytes
- `GET` object bytes
- `HEAD` object metadata
- `HEAD` bucket readiness probe

There is no delete, copy, lifecycle, migration, archival, restore, or disposal method.

Requests use bounded AWS Signature Version 4 signing compatible with AWS S3, MinIO, and equivalent path-style S3 endpoints that do not require an endpoint path prefix.

### 4. Integrity remains application-verifiable

Foundation uploads store the SHA-256 digest in `x-amz-meta-mcri-sha256`. Reads recompute SHA-256 and fail closed if the bytes differ from either the caller-provided authoritative evidence hash or the stored MCRI hash metadata.

Object metadata without the MCRI integrity hash is not treated as verified MCRI evidence.

### 5. Object authority remains application-generated

The foundation provides deterministic managed evidence keys scoped by organization, claim, and document UUID. Validation rejects traversal-like segments, control characters, invalid suffixes, and keys outside the expected tenant/claim prefix.

A future cutover must continue to derive keys from authoritative application identifiers rather than accepting caller-supplied bucket/key authority.

### 6. No destructive-disposal authority follows from storage readiness

A reachable S3 target does not make an approved Phase 17.2-H release review executable. Phase 17.3-A creates no disposal token, worker, queue payload, object deletion route, database hard-delete path, lifecycle policy, or timer-driven action.

## Consequences

### Positive

- recovery-capable object storage can be configured and connectivity-tested before cutover
- no cloud SDK dependency is added in this tranche
- supply-chain surface remains unchanged
- S3 credentials remain separated from runtime health output
- integrity semantics are explicit and testable
- accidental partial cutover fails closed
- physical disposal remains blocked until storage recovery/cutover controls are deliberately reviewed

### Trade-offs

- S3 cannot yet receive live admitted evidence from the document API
- existing local evidence is not migrated or replicated
- quarantine-safe S3 admission, malware scanning strategy, dual-read/dual-write, recovery proof, and cutover require later bounded tranches
- the minimal SigV4 client supports the subset required for foundation readiness rather than every S3 feature

## Follow-up

Phase 17.3-B should design a **non-destructive evidence replication and recovery-verification layer** from local authoritative evidence to the configured S3 target. It should pin source document IDs/hashes, verify copied bytes, support replay/idempotency, avoid deleting either source or target objects, and provide restore-readiness evidence before any active-storage cutover or irreversible disposal executor is considered.
