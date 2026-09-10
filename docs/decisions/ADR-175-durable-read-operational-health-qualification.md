# ADR-175: Durable read operational health qualification

## Status
Accepted for Phase 17.3-N implementation.

## Context
Phase 17.3-M introduced the first bounded durable recovery read-routing lease. It can temporarily route verified document reads to the recovery replica for at most 24 hours and can return the shared read route to the intact local source through explicit rollback or expiry reconciliation.

A successful activation alone must not become evidence that durable recovery reads are safe to renew or promote again. A later decision needs explicit proof of what happened during the exact Phase M operational window: whether recovery bytes were actually read successfully, whether integrity or lineage checks failed, whether object storage was unavailable, and whether the route returned cleanly to local authority.

The platform already emits immutable audit records for successful document downloads. Phase N extends this evidence with bounded failure-class audit events for durable recovery reads. These records are evidence only; they cannot create routing authority or storage authority.

## Decision
Add a non-routable `EvidenceRecoveryDurableReadHealthQualification` bound to one exact terminal Phase M durable read lease.

A health qualification may be requested only when the Phase M lease is terminal `rolled_back` or `expired` and its activation and terminal transition receipts are intact. The current shared read route must exactly match the clean `local_source` state produced by that terminal transition.

The qualification snapshot binds:

- the exact Phase M lease, authorization, Phase K qualification and recovery replica lineage;
- the exact activation and terminal receipts;
- the activation-to-terminal time window;
- the current clean local route and route version;
- fresh local-source SHA-256, byte length and storage-key fingerprint verification;
- fresh recovery-replica lineage plus remote byte verification;
- immutable operational audit evidence for the exact durable lease and window.

At least one successful `recovery-replica-durable` document read is required. A lease that was activated and immediately returned to local without a verified recovery read cannot be qualified.

Operational evidence is classified as follows:

- `healthy`: at least one verified durable recovery read and no integrity/lineage failure or storage-unavailable event;
- `degraded`: verified recovery reads exist, but at least one transient storage-unavailable event occurred;
- `failed`: verified recovery reads exist, but at least one integrity or lineage failure occurred.

An attempted read after the bounded route expiry is recorded separately as `route_expired`. This is expected fail-closed lease behavior and is counted for operational analysis, but by itself does not downgrade integrity health.

A second Admin with current tenant MFA must assess the pending qualification. The qualifier must differ from both the requester and the Phase M durable-route activator. Fresh local, replica, route and operational-evidence verification is repeated immediately before the second decision.

Only `health_state=healthy` can transition to `qualified`. A non-healthy snapshot transitions to `degraded`, never silently to qualified. A human may also explicitly reject a pending qualification. Lineage or evidence drift invalidates a pending qualification fail closed. Temporary storage unavailability during fresh verification returns retryable service unavailability and does not manufacture a decision.

Qualification and transition receipts are hash-bound and append-only. API and audit payloads contain IDs, hashes, counts and fingerprints only; raw local or recovery storage keys are not persisted in Phase N governance evidence.

## Safety boundary
Phase 17.3-N is governance and operational-evidence qualification only.

It does not:

- create, activate, extend or renew any recovery read route;
- switch the document write path;
- mutate `Document.storage_key`;
- make S3/recovery storage authoritative evidence ownership;
- overwrite, move or delete authoritative local evidence;
- perform S3 COPY, DELETE or lifecycle mutation;
- create dual-write authority;
- create disposal or destructive execution authority.

Database constraints keep `routable_authority_created`, `durable_read_route_created`, `read_path_switched`, `write_path_switched`, `document_storage_key_mutated`, `authoritative_storage_changed`, `destructive_action_performed`, `s3_delete_performed` and `local_delete_performed` false for Phase N qualification records and receipts.

## Consequences
A future renewal or broader durable-read promotion phase can require one or more exact Phase N `qualified` records rather than treating a Phase M activation as implicit proof of health. Degraded or failed windows remain visible evidence and cannot be erased by later successful reads.

Write-path migration, authoritative storage promotion, dual-write and local evidence retirement remain separate future decisions and require their own explicit governance, recovery proof, tests and production gates.
