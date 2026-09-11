# ADR-189: Independent health qualification for a completed routable dual-write canary

## Status
Accepted for Phase 17.3-AC implementation.

## Context
Phase 17.3-AB introduced the first bounded secondary recovery write canary. During that window local evidence remained authoritative, the read route stayed local, and a dedicated write-routing control plane temporarily moved from `local_only` to `local_plus_recovery_canary`. AB then restored the write route to `local_only` by explicit rollback or expiry and retained the isolated canary object as inert evidence.

A successful execution receipt is not sufficient evidence for stronger write authority. The platform needs an independent review after the canary has ended, so that the completed window, terminal rollback, local source, shared routes, lineage and remote canary bytes are all revalidated from current state.

## Decision
Phase AC creates an evidence-only operational-health qualification for exactly one completed AB canary lease.

Admission requires the AB lease to be terminal `rolled_back` or `expired`, with exactly one activation receipt and exactly one receipt matching the terminal state. The activation must show `local_only → local_plus_recovery_canary`; the terminal receipt must show `local_plus_recovery_canary → local_only`.

The dedicated AB write route must be `local_only`, have no active canary pointer and be exactly one route version after the activation route version. The pre-existing read route must still be exact local authority with no recovery read pointer. `Document.storage_key` and authoritative local bytes must still match the AB lineage.

The deterministic AB canary key is reconstructed rather than stored as a routable key. AC performs HEAD and GET only, validates exact SHA-256 and byte length, checks the recovery bucket identity and compares the observed ETag when AB recorded one. AC never calls PUT, COPY, DELETE or lifecycle mutation operations.

Request and qualification are separate Admin+MFA actions. The qualifier must differ from the AC requester, AB activator, AA requester, AA approver, Z qualifier, Y executor and X approver. A ten-minute independent review window is used. The second action performs the entire fresh verification again. Recovery-storage outage is retryable and leaves a pending qualification pending. Route, lineage or integrity drift invalidates the pending qualification fail-closed.

## Persistence
AC stores one qualification row per AB lease and append-only transition receipts. The qualification binds:

- AB lease, activation receipt and terminal receipt IDs and hashes;
- AA authorization and approval receipt;
- Z qualification, Y execution, X authorization and replica lineage hashes;
- local source hash, byte length and storage-key fingerprint;
- recovery bucket and replica-key fingerprints;
- canary key fingerprint and freshly observed remote evidence;
- exact read-route and terminal write-route versions;
- integrity-proof, request-snapshot and health-qualification hashes;
- governance actors used for Four-Eyes enforcement.

Database constraints keep `local_authoritative=true` and permanently lock the following AC facts to false: storage write performed, canary reactivated, routable dual-write active, durable write authority created, read/write path switched, document storage key mutated, authoritative storage changed, destructive action performed, S3 PUT/COPY/DELETE performed and local delete performed.

## Consequences
A qualified AC artifact proves that one completed AB canary window returned to exact local-only authority and still has byte-identical inert recovery evidence at independent review time. It does **not** authorize or execute another canary, durable dual-write, write-path replacement, authoritative-storage migration or disposal.

Any later phase that proposes stronger write authority must consume AC explicitly and add its own bounded governance and rollback semantics.
