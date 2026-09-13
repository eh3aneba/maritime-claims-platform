# ADR-209: Govern external provider credential-reference custody without secret custody

## Status
Accepted for Phase 17.5-E implementation.

## Context
Phases 17.5-A through 17.5-D establish a governed external document source, metadata-only discovery, four-eyes bootstrap authorization and one-use consumption of that authorization. Phase 17.5-D deliberately stops before credential custody or provider connectivity.

A future SharePoint / Google Drive provider client will need a way to identify where its credential is managed without putting the credential itself into application tables. That locator is operationally sensitive governance metadata and must not be accepted as an unstructured URI that could embed secrets.

## Decision
Phase 17.5-E introduces one credential-reference binding per completed Phase 17.5-D bootstrap execution.

A binding stores only canonical locator metadata:
- one supported secret-manager backend;
- a constrained namespace identifier;
- a constrained secret-name identifier; and
- an optional constrained version label.

Supported backends in this tranche are `aws_secrets_manager`, `azure_key_vault`, `gcp_secret_manager` and `hashicorp_vault`.

The API does not accept a generic URL/URI field. Locator components reject whitespace, URL delimiters, query strings, fragments, assignment syntax and common token/key signatures. Request schemas reject unknown fields so secret values cannot be silently submitted as ignored properties.

### Admission chain
A request requires:
- one exact completed, integrity-valid Phase 17.5-D bootstrap execution;
- its exact Phase 17.5-A / 17.5-B / 17.5-C lineage;
- the bound source profile still `active`; and
- one Admin + MFA requester.

A different Admin + MFA actor must approve the binding.

Each Phase 17.5-D execution may bind at most one credential reference. Replacing a reference therefore requires a newly governed upstream authorization/bootstrap chain rather than silently rebinding existing authority.

### Lifecycle
The lifecycle is:
- `pending_second_approval → active`; or
- `pending_second_approval → rejected`; and
- `active → disabled`.

Every transition emits an append-only hash-chained receipt. Exact replay is idempotent; changed replay conflicts.

A pending or active binding is usable as governance state only while the bound source profile remains active. If the source profile is disabled, reads/approval fail closed. Historical rejected/disabled bindings remain readable for audit.

### Integrity
The binding hash lineage includes:
- tenant/profile/provider identity and exact profile hash;
- exact Phase 17.5-D execution ID, scope/request/completion hashes and authorization terminal hash;
- canonical credential-reference locator hash;
- request key, requester, reason and timestamp;
- independent approval facts; and
- terminal facts for rejection/disable.

Receipt validation cross-checks sequence, event, actor, time, reason, status, decision hash, prior hash and safety facts against the binding record.

### Safety boundary
`credential_reference_stored=true` means only that canonical non-secret locator metadata is stored in this governance record. It does not mean the application possesses or can resolve a credential.

Phase 17.5-E performs none of the following:
- raw credential/password/client-secret/private-key storage;
- OAuth authorization-code/access-token/refresh-token storage or exchange;
- secret-manager fetch/resolve operations;
- Microsoft Graph or Google Drive client registration/network traffic;
- remote list/read/write/move/delete;
- provider subscription or sync checkpoint creation;
- Evidence admission;
- Document creation; or
- claim mutation.

Database constraints keep all such execution facts false.

## Consequences
The platform gains a reviewable, cryptographically bound pointer to externally managed credential material without widening authority to retrieve that material. Secret resolution and OAuth/token exchange remain separate future authority increases.

## Verification
Release requires a real A→B→C→D→E chain, four-eyes approval, exact replay and changed replay conflict, strict locator/input rejection, source-profile fail-closed behavior, rejection/disable, tenant isolation, receipt-tamper rejection, and proof of zero raw-secret/provider/evidence/document/claim execution.

References: #410, ADR-208.
