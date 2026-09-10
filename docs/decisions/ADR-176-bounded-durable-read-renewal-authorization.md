# ADR-176: Bounded durable recovery read renewal authorization

## Status

Accepted for Phase 17.3-O implementation review.

## Context

Phase 17.3-M proved a bounded durable recovery read route and returned the shared route to authoritative local reads. Phase 17.3-N then classified the exact completed Phase M window from immutable transition receipts plus observed read/failure audit evidence and fresh local/recovery integrity checks.

A later durable-read window must not be authorized merely because Phase M once succeeded. Renewal needs an explicit governance decision that consumes the exact **qualified, healthy** Phase N result and proves that its lineage, source bytes, recovery replica, route state and configuration have not drifted.

## Decision

Phase 17.3-O introduces a non-routable `EvidenceRecoveryDurableReadRenewalAuthorization` and append-only transition receipts.

A request may consume exactly one Phase N health qualification only when all of the following remain true:

- Phase N status is `qualified` and `health_state=healthy`.
- The health qualification has exactly one intact `qualified` receipt.
- At least one verified durable recovery read occurred in the completed Phase M window.
- Integrity-failure and object-storage-unavailability counts are zero.
- The complete Phase N snapshot can be freshly reconstructed and exactly matches the stored qualification.
- The shared read route is still clean `local_source`, has no active temporary or durable recovery lease/replica, and remains at the Phase N terminal route version.
- Local-source and recovery-replica integrity still match the same hashes, sizes and authority/configuration fingerprints.

Each health qualification can back at most one Phase O authorization. A new future renewal therefore requires fresh completed operational-health evidence rather than indefinite reuse of one historic healthy window.

The authorization state machine is:

`pending_second_approval -> approved | rejected | expired | invalidated`

The approval window is capped at ten minutes. Expiry never creates routing authority. Request and approval re-run the complete fresh preflight. Integrity or lineage drift invalidates a pending authorization fail-closed. A transient recovery-storage availability failure remains retryable: the API returns `503` and the pending authorization is left unchanged so a later retry can re-run the full preflight inside the bounded approval window.

Four-eyes rules require the approver to differ from:

- the Phase O requester;
- the Phase N health qualifier; and
- the prior Phase M durable-route activator.

Mutations require Admin + MFA. Admin and Claims Manager may read records and receipts. All lookups are tenant/claim/document scoped, so cross-tenant identifiers resolve as `404`.

## Safety boundary

Phase O is governance authorization only. Even `approved` is **not** a route, execution lease, write authority, storage-ownership change, or disposal authority.

Database constraints pin all authorization and receipt records to:

- `routable_authority_created=false`
- `durable_read_route_created=false`
- `read_path_switched=false`
- `write_path_switched=false`
- `document_storage_key_mutated=false`
- `authoritative_storage_changed=false`
- `destructive_action_performed=false`
- `s3_delete_performed=false`
- `local_delete_performed=false`

This tranche performs no route renewal or extension, no `Document.storage_key` rewrite, no local overwrite/move/delete, no S3 COPY/DELETE/lifecycle mutation, no dual-write, no authoritative recovery-storage promotion, no write-path migration and no evidence disposal.

Audit payloads contain only IDs, hashes, fingerprints, health counters and explicit safety flags. Raw local or recovery storage keys and raw storage-failure text are excluded.

## Consequences

A later separately reviewed Phase 17.3-P may consume one exact approved, unexpired Phase O authorization as a prerequisite for preparing another bounded durable-read routing lease. Phase P must independently revalidate this lineage and remains separate from any write-path or evidence-ownership migration.

This preserves the progression:

`reversible read proof -> repeated qualification -> durable-read authorization -> bounded durable read -> operational health -> renewal authorization`

without treating read reliability as permission to migrate write authority or evidence ownership.
