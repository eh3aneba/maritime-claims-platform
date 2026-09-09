# ADR-160: Reversible logical quarantine staging before any physical disposal

- Status: Accepted
- Date: 2026-09-09
- Decision owners: MCRI enterprise retention governance
- Related: ADR-154, ADR-155, ADR-156, ADR-157, ADR-158, ADR-159

## Context

MCRI now has a preservation-first disposal governance chain:

1. tenant retention policy and formal legal holds,
2. pending automated hold proposals as disposal blockers,
3. signed preservation-signal intake,
4. four-eyes `DisposalAuthorization`,
5. immutable `DisposalExecutionManifest`, and
6. independently attested, non-destructive `DisposalDryRunCeremony`.

The next useful control is a reversible staging state that can represent a quarantine decision without creating an irreversible action or delegating deletion authority to software.

A physical move, archive, tombstone, object-store lifecycle change, or database soft/hard delete would materially change evidence availability and recovery risk. Phase 17.2-G therefore stops before those actions.

## Decision

Introduce `DisposalQuarantineStage` as a tenant- and claim-scoped **logical governance overlay only**.

A stage may be created only when:

- the linked dry-run ceremony is `attested`,
- the ceremony remains inside its validity window,
- stored ceremony and attestation hashes validate,
- the linked execution manifest revalidates as `ready`,
- the manifest, authorization, policy, inventory and dry-run plan lineage remain exact,
- no active legal hold or pending legal-hold proposal has appeared, and
- current claim/evidence/storage fingerprints still match the pinned lineage.

The stage pins:

- dry-run ceremony ID/hash and attestation hash,
- execution manifest and authorization lineage,
- retention policy lineage,
- deterministic logical overlay plan,
- overlay hash and stage hash,
- document count and total file bytes,
- stage actor, reason and bounded validity window.

The logical overlay plan contains only IDs, row fingerprints, file hashes, storage-key fingerprints, byte counts and bounded version metadata. It stores no raw storage key and no file content.

The stage lifecycle is:

`staged | restored | invalidated | expired | cancelled`

`staged` means only that the governance overlay is active. It does not mean that content has moved or become unavailable.

## Revalidation

Every stage mutation is fail closed.

Before revalidation, restoration or cancellation, MCRI checks the stored stage integrity and re-runs the upstream dry-run/manifest preservation checks. Policy drift, claim/evidence/storage drift, active legal hold, pending legal-hold proposal, authorization expiry, manifest expiry, ceremony expiry or integrity mismatch terminalizes the stage as `invalidated` or `expired`.

No timer or background worker performs a physical action when the window expires.

## Restoration

Restoration only transitions the logical overlay from `staged` to `restored` after a fresh preservation check. Because source data was never moved or deleted, restoration cannot lose evidence and does not need any destructive credential or storage operation.

## Authority

- Read: local Admin or Claims Manager.
- Create/revalidate/restore/cancel: local Admin with current tenant MFA.
- AI, rules, webhooks, external signals, service accounts, timers and workers cannot create or restore a stage.

## Explicitly excluded from Phase 17.2-G

- database `DELETE`,
- `Claim.deleted_at` or `Document.deleted_at` mutation,
- object-store delete,
- object-store move/rename,
- archive/lifecycle mutation,
- physical quarantine bucket or namespace move,
- physical tombstone,
- destructive worker or queue,
- execution token, credential or runnable payload,
- timer-triggered follow-on action,
- irreversible disposal.

Audit records explicitly state:

- `logical_overlay_only=true`,
- `physical_quarantine_performed=false`,
- `execution_authority_created=false`, and
- `destructive_action_performed=false`.

## Consequences

### Positive

- Adds another human-governed boundary before any destructive capability.
- Preserves exact lineage from policy through authorization, manifest, dry run and quarantine overlay.
- Makes rollback trivial because source content is untouched.
- Ensures a new preservation signal invalidates the disposal path before any physical change.

### Trade-offs

- This phase does not reduce storage consumption.
- `staged` is governance metadata, not physical isolation.
- A future physical quarantine capability will require separate threat modeling, recovery guarantees, explicit user approval, and a new ADR/PR.

## Follow-up

A later phase may consider **physical but reversible quarantine** only if it can guarantee recovery, preservation-signal override, object-integrity verification, bounded human authority, and no silent escalation to irreversible deletion. Irreversible disposal remains a separately reviewed future decision.
