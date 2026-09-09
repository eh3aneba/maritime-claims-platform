# ADR-158: Govern disposal execution through a non-destructive manifest preflight

- Status: Accepted
- Date: 2026-09-09
- Decision owners: MCRI retention governance
- Related: #25, #298, #299, #300

## Context

Phase 17.2-D introduced a four-eyes `DisposalAuthorization` that records local human authority after retention eligibility, legal-hold, pending-proposal, policy, claim, and evidence checks pass. That authorization deliberately does not execute disposal.

A later destructive executor must not infer its target set from mutable live data without a separately reviewable boundary. Between authorization and any future execution, claim state, document metadata, storage locations, retention policy lineage, or preservation duties can change. A timer or an approved authorization alone must never become deletion authority.

## Decision

MCRI introduces a tenant-scoped `DisposalExecutionManifest` as a **non-destructive preflight artifact** between an approved disposal authorization and any future executor.

A manifest may be created only when all of the following are true at creation time:

1. the referenced `DisposalAuthorization` belongs to the same tenant and claim;
2. the authorization is still `approved` and has complete approval lineage;
3. the authorization has not expired;
4. the current retention policy id, version, and hash still match the authorization;
5. the claim/evidence retention anchors and expiry timestamps still match the authorization;
6. the claim/evidence state fingerprint still matches the authorization;
7. the current disposal eligibility preview remains eligible;
8. there are no active `ClaimLegalHold` records; and
9. there are no pending `LegalHoldProposal` records.

Manifest creation and revalidation require a local Admin and the current tenant MFA policy. Admins and Claims Managers may read manifests.

### Inventory design

The manifest inventories the exact governed objects that a future executor would need to resolve again. It records:

- the claim identifier and state fingerprint;
- each Document identifier and family identifier;
- file hash, file size, MIME type, version/current state, processing state, malware state, update/delete timestamps;
- a SHA-256 fingerprint of each storage key; and
- a canonical row fingerprint for each inventory entry.

Raw file contents are never embedded in the manifest. Raw storage keys are not persisted in the manifest and are not written into the manifest audit payload; only storage-key fingerprints are retained. A future executor therefore must resolve live storage metadata again and prove that it still matches the manifest.

The complete inventory is canonicalized and SHA-256 hashed. A second manifest hash binds the inventory hash to the approved authorization lineage, authorization snapshot/state fingerprints, retention policy lineage, evaluation time, and manifest expiry.

### Lifecycle and validity

The manifest lifecycle is bounded to:

- `ready`
- `blocked`
- `invalidated`
- `expired`

A ready manifest is valid for at most four hours and never beyond its parent authorization expiry.

Revalidation recomputes the authorization, preservation controls, policy lineage, claim/evidence state, and object/storage inventory. Results are fail-closed:

- a newly active legal hold or pending legal-hold proposal makes the manifest `blocked`;
- authorization, policy, claim, evidence, or storage/inventory drift makes it `invalidated`;
- elapsed validity makes it `expired`;
- internal manifest/hash integrity failure makes it `invalidated`.

Terminal manifests are not revived. Only one manifest may be created from one disposal authorization. A fresh manifest after terminalization therefore requires a fresh disposal authorization and a new human review chain.

## Explicitly not authorized by this ADR

This decision does **not** authorize or implement:

- a DELETE endpoint;
- mutation of `Claim.deleted_at` or `Document.deleted_at`;
- physical object-store deletion;
- archive/move/tombstone/lifecycle-policy mutation;
- a bulk disposal worker;
- timer-driven execution;
- AI-, rule-, webhook-, external-signal-, or service-account self-authorization; or
- any irreversible action.

An audit record for manifest operations explicitly records that no destructive action was performed.

## Consequences

### Positive

- A future destructive executor can be constrained to an exact, cryptographically pinned inventory rather than mutable query results.
- Preservation changes remain immediate blockers after authorization.
- Storage-location drift can be detected without persisting raw storage identifiers in the governance artifact.
- The authorization decision and the execution target set remain separate auditable control planes.

### Costs

- A new database table, migration, API surface, and revalidation step are required.
- A manifest can expire or invalidate frequently when claim/evidence/storage metadata changes; this is intentional fail-closed behavior.
- A later executor must still independently resolve and verify live storage/object state.

## Future work

If a Phase 17.2-F destructive executor is justified, it must be reviewed and authorized separately. Before any irreversible mutation it must, at minimum, perform a final atomic preservation/policy/authorization/manifest revalidation, define referential-integrity behavior, coordinate explicitly with the configured storage backend, produce an immutable execution receipt, and have a documented recovery/rollback or irreversibility policy.

No future phase may convert timer expiry or manifest readiness into automatic deletion authority.
