# ADR-125: Provider credential reference lifecycle and metadata minimization

## Status
Accepted for Phase 15.8 implementation.

## Context
Graph and Gmail provider adapters need an external credential locator so runtime execution can obtain a credential without storing the bearer secret in the application database. The previous adapter API and audit surface exposed that locator and provider checkpoint fingerprints more broadly than necessary.

A credential reference is not itself the bearer credential, but it is sensitive operational metadata. It can reveal environment-variable names, Vault paths, Secret Manager identifiers, deployment structure, or credential custody conventions. A checkpoint hash is likewise internal synchronization metadata and is not needed by ordinary API consumers.

The repository currently has a real process-environment resolver for `env://` references. It does not contain a configured Vault or cloud Secret Manager client. Pretending those external stores are available would turn a fail-closed boundary into an unsafe assumption.

## Decision

### 1. Credential locator stays internal
The raw `credential_reference` remains an internal adapter persistence/runtime field. Normal adapter, run, reconciliation, and audit responses must not expose the locator.

Safe operational metadata may expose only:
- credential backend category: `env`, `vault`, `secret-manager`, or `invalid`;
- whether a reference is configured;
- whether the current application runtime has a resolver for that backend;
- non-secret reference version;
- last reference change timestamp.

Legacy malformed references are classified only as `invalid`; their text must never be reflected as a backend label.

### 2. Checkpoint fingerprints stay internal
Raw provider checkpoints remain response-only at the governed handoff boundary defined by ADR-124. Stored checkpoint hashes remain internal persistence data.

Ordinary adapter and run APIs expose only a boolean `checkpoint_present`. They do not expose `checkpoint_hash`.

### 3. Creation audit is content-free
Creating an adapter records only bounded provider kind, allowed-folder permission metadata, credential backend, resolver availability, reference configured/version state, and other non-secret operational facts.

It must not record the credential locator, resolved bearer credential, raw checkpoint, or checkpoint hash.

### 4. Credential reference rotation is explicit operator authority
Only an Admin or Claims Manager may rotate an adapter credential reference. The action requires:
- tenant-scoped adapter access;
- a non-revoked adapter;
- explicit confirmation;
- a human reason of at least 20 characters;
- a syntactically valid supported reference scheme;
- no pending provider checkpoint handoff.

Rotation changes only the external credential reference and its non-secret lifecycle metadata. It does not call Graph, Gmail, Vault, Secret Manager, or any other provider.

The existing acknowledged provider checkpoint, staged messages, canonical Correspondence, attachment quarantine, Evidence, Documents, processing state, Claim Facts, reserves, settlements, and other claim state remain unchanged.

An active Graph/Gmail source with an active consented connection becomes due for an explicit pull after rotation. A suspended or otherwise inactive source remains unscheduled.

### 5. Rotation audit excludes locator and reason text
Rotation audit stores only bounded before/after backend categories, reference version, resolver availability, confirmation that a reason was supplied, and whether the previous checkpoint was preserved.

The raw old/new credential locator and the human reason text are intentionally not persisted in audit metadata because operators may accidentally paste secrets or sensitive infrastructure details into either field.

### 6. Resolver availability remains fail-closed
`env://` credentials are resolved only at execution time from the process environment and the resolved value is not persisted.

`vault://` and `secret-manager://` are valid external-reference categories but remain `credential_resolver_unavailable` until a real repository-backed client/configuration is implemented and separately governed. Phase 15.8 does not simulate those backends, map them to environment variables, or weaken the failure mode.

### 7. Legacy invalid references can be repaired
If an existing installation contains a legacy malformed reference, reconciliation reports only backend `invalid`. A manager/admin may replace it with a valid reference through the governed rotation action. The malformed locator itself is never emitted to the API or audit log.

## Authority boundary
This ADR does not add provider send, modify, delete, auto-link, Correspondence promotion, Evidence admission, document processing, AI decision, coverage, causation, liability, reserve, settlement, payment, or claim-closure authority.

Credential rotation is operational configuration only. Provider execution and all downstream claim authorities remain separately governed.

## Consequences
- Secret locators and checkpoint fingerprints have a smaller disclosure surface.
- Credential-reference changes become explicit, versioned, auditable operational actions.
- External secret-store support remains honest and fail-closed until real infrastructure exists.
- Operators can repair legacy invalid references without exposing them.
- Existing provider checkpoints and canonical claim state are preserved across rotation.
