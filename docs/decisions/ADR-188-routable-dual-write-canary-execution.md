# ADR-188: Bounded routable dual-write canary execution

## Status
Accepted for Phase 17.3-AB.

## Context
Phase 17.3-AA authorizes exactly one future bounded routable dual-write canary after a qualified Phase Z rehearsal-health artifact. The authorization itself deliberately performs no write and creates no runtime write authority.

The next step must prove that MCRI can execute one controlled secondary recovery write without changing the authoritative local storage path, without coupling read routing to write routing, and without introducing destructive rollback semantics.

A production-wide dual-write hook is explicitly premature. A local write and an S3 write are not one atomic transaction, and silently wiring every normal document mutation into both backends would create split-brain and ambiguous retry behavior before the control plane has been qualified.

## Decision
Phase AB executes one bounded canary operation under one approved and unexpired Phase AA authorization.

### Dedicated write-routing control plane
AB does not reuse or mutate the existing recovery read-route pointer. It introduces one write-routing record per document with only two modes:

- `local_only`
- `local_plus_recovery_canary`

During an active canary lease the write-route points to exactly one AB lease. The existing read route remains `local_source` with local authority throughout.

`write_path_switched` remains `false`. This flag means the authoritative write path has not switched away from local. The recovery operation is a bounded secondary canary only.

### One bounded canary object
The canary object key is deterministic and isolated:

`canary/routable-dual-write/<organization>/<claim>/<document>/<aa-authorization><suffix>`

It must never equal `Document.storage_key` or the verified recovery-replica key. The key itself is not persisted as a routable production key; only its SHA-256 fingerprint is retained in the lease and receipts.

Before creating the object, AB performs HEAD-before-PUT. If absent, it uses conditional create-only semantics (`If-None-Match: *`). If an object already exists, it is reusable only when its stored SHA-256 and byte length exactly match the authoritative local snapshot. A mismatch fails closed and is never overwritten.

After create/reuse, AB verifies the object through HEAD + GET and recomputes SHA-256 and byte length. The verification is repeated before the lease is admitted as active.

### Fresh admission
Immediately before the canary operation AB revalidates:

- exact approved and unexpired Phase AA authorization;
- exact AA approved receipt;
- AA → Z → Y → X → W → V → U → T → replica lineage;
- the Phase Z fresh-verification path and AA immutable snapshot;
- clean local read-route authority;
- authoritative local evidence hash, size and storage-key fingerprint;
- recovery replica lineage and configured recovery bucket;
- clean `local_only` AB write route.

Recovery-storage outages remain retryable. Lineage, route, key or integrity drift fails closed.

### Governance
Mutations require tenant-local Admin + MFA. Reads remain available to Admin and Claims Manager under the retention reader policy.

The operational activator must differ from the AA requester, AA approver, Phase Z qualifier, Phase Y executor and Phase X approver.

One AA authorization may create at most one AB canary lease. The active window is limited to ten minutes and one verified secondary canary write.

### Rollback
Rollback is control-plane/logical rather than destructive:

- the write route returns to `local_only`;
- `active_canary_lease_id` is cleared;
- the lease becomes `rolled_back` or `expired`;
- append-only terminal evidence is recorded;
- the verified canary object remains inert, non-routable and non-authoritative.

AB introduces no S3 DELETE authority solely for rollback.

## Safety invariants
Throughout Phase AB:

- local evidence remains authoritative;
- the existing read path remains local;
- the authoritative write path is not replaced;
- `Document.storage_key` is not mutated;
- storage ownership does not change;
- no durable/permanent write authority is created;
- the Phase Y rehearsal object does not become routable;
- no mismatched remote object is overwritten;
- no S3 COPY, DELETE or lifecycle mutation is issued;
- authoritative local evidence is not moved, overwritten or deleted;
- no disposal authority is introduced.

These invariants are duplicated as database constraints on leases, routes and receipts.

## Failure and retry semantics
A remote outage before successful verification returns a retryable unavailable result and the database transaction does not consume the canary lease. If the remote PUT succeeded but its response was lost, the deterministic key and HEAD-before-PUT logic allow a retry to reconcile the exact object without a second overwrite.

A remote object with a different hash or size is a terminal conflict for that attempt and is never overwritten.

## Non-goals
Phase AB does not:

- connect the normal document write path to production-wide dual-write;
- make recovery storage authoritative;
- switch reads to recovery;
- promote recovery storage ownership;
- create permanent or durable write authority;
- delete the canary object after rollback;
- authorize disposal.

## Consequences
AB proves a bounded, observable secondary-write control plane while preserving exact local authority. The next phase should independently qualify one completed and cleanly terminated AB window before any broader document-write integration or stronger write authority is considered.
