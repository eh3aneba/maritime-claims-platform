# ADR-166 — Non-authoritative recovery shadow promotion rehearsal

## Status

Proposed for Phase 17.3-E.

## Context

Phase 17.3-C proves that verified recovery bytes can be restored into isolated staging. Phase 17.3-D adds a four-eyes promotion attestation that binds an exact recovery replica, restore rehearsal, latest restore verification, configuration fingerprint and non-executable promotion plan.

A remaining gap is operational proof that the exact approved candidate can be materialized into a cutover-shaped target without changing evidence authority. Jumping directly from attestation to an authoritative storage switch would combine rehearsal and cutover risk in one step.

## Decision

Introduce an immutable `EvidenceRecoveryShadowPromotion` and append-only `EvidenceRecoveryShadowVerification` history.

A shadow rehearsal may be created only from an approved, unexpired `EvidenceRecoveryPromotionAttestation`. Creation and every re-verification freshly validate:

- authoritative local source integrity;
- recovery replica and remote object integrity;
- restore staging integrity;
- exact restore verification lineage;
- attestation request snapshot, promotion plan and configuration fingerprints;
- the attestation's explicit non-cutover safety contract.

The approved candidate is copied from verified restore staging into a deterministic `recovery-shadow-promotion/...` namespace using atomic no-overwrite publication. Existing ungoverned targets are never adopted or overwritten. The raw shadow key remains internal and only fingerprints are exposed through APIs and audit events.

## Hard safety boundary

Phase 17.3-E does **not**:

- rewrite `Document.storage_key`;
- change the active document storage backend;
- move, overwrite, archive or delete authoritative evidence;
- issue S3 COPY, DELETE or lifecycle mutations;
- enable dual-write admission;
- create an authoritative recovery pointer;
- create an irreversible cutover or destructive execution token.

Shadow materialization is evidence that a promotion candidate can be created and verified. It is not authority to switch storage.

## Failure semantics

The workflow fails closed when the attestation is not approved, has expired, or any source/replica/staging/verification/configuration/promotion-plan lineage changes. Unknown pre-existing shadow targets, shadow tamper and cross-tenant access are rejected. A terminally stale attestation cannot be used to refresh a shadow rehearsal.

## Access and audit

Create/reverify operations require a local Admin session satisfying current tenant MFA. Admin and Claims Manager roles may read. Audit payloads contain hashes/fingerprints only and explicitly record:

- `cutover_performed=false`;
- `authoritative_storage_changed=false`;
- `source_storage_key_mutated=false`;
- `destructive_action_performed=false`.

## Consequences

A later tranche may design a reversible authority-switch rehearsal or bounded cutover contract, but it must be separately governed and cannot infer execution authority from a shadow rehearsal alone.
