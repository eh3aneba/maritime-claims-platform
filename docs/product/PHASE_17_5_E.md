# Phase 17.5-E — Governed external provider credential-reference custody

## Goal
Bind one completed Phase 17.5-D bootstrap execution to one governed, non-secret credential locator for a future SharePoint / Google Drive provider client without storing or resolving any credential material.

## Admission chain
A request must bind to:
- one active Phase 17.5-A external document source profile;
- its integrity-valid Phase 17.5-B discovery lineage;
- its exact Phase 17.5-C authorization lineage;
- one completed integrity-valid Phase 17.5-D bootstrap execution; and
- one Admin + MFA requester.

A different Admin + MFA actor must approve the binding before it becomes `active`.

## Canonical locator
Phase E stores only:
- `reference_backend` — one of `aws_secrets_manager`, `azure_key_vault`, `gcp_secret_manager`, `hashicorp_vault`;
- `reference_namespace` — constrained non-secret identifier;
- `reference_name` — constrained non-secret identifier; and
- optional `reference_version` — constrained non-secret version label.

The service stores no generic secret URI and no raw credential value. Locator components are normalized, validated and SHA-256 bound as `locator_hash`.

Unknown request fields are rejected. URL/query/fragment/assignment syntax and common token/key signatures are rejected from locator components.

## Lifecycle
The lifecycle is:
- `pending_second_approval → active`;
- `pending_second_approval → rejected`; or
- `active → disabled`.

Receipts are respectively:
- `requested`;
- `requested → approved`;
- `requested → rejected`; or
- `requested → approved → disabled`.

Each completed Phase 17.5-D bootstrap execution can have at most one Phase E binding. Exact replay returns the same binding; changed replay conflicts.

## Integrity
The binding records and hashes:
- organization/profile/provider identity;
- exact profile hash;
- exact Phase D execution ID;
- Phase D scope, request and completion hashes;
- exact Phase C authorization terminal hash carried by Phase D;
- canonical locator hash;
- request key and request facts;
- independent approval facts; and
- rejection/disable terminal facts.

Every read recomputes the full lineage and receipt chain.

For pending/active bindings, the bound source profile must still be `active`; otherwise access fails closed. Rejected/disabled bindings remain readable for historical audit.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/bootstrap-executions/{execution_id}/credential-reference-bindings`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/approve`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/reject`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/receipts`

All endpoints require Admin + MFA.

## Safety boundary
`credential_reference_stored=true` is a narrow fact: the application stores only canonical non-secret locator metadata.

The following remain false throughout Phase 17.5-E:
- `credential_stored`;
- `oauth_token_exchanged`;
- `provider_network_performed`;
- remote list/read/write/delete;
- subscription creation;
- synchronization execution;
- Evidence admission;
- Document creation; and
- claim mutation.

Phase E does not resolve the secret-manager reference, register a production provider client, exchange OAuth tokens, read remote content or admit evidence.

## Acceptance coverage
- real Phase 17.5-A → B → C → D → E chain;
- one binding per completed Phase D execution;
- independent Admin + MFA approval;
- exact replay and changed replay conflict;
- unknown-field, URL-like and secret-like locator rejection;
- source-profile fail-closed behavior;
- rejection and explicit disable;
- tenant isolation;
- receipt-tamper rejection; and
- zero raw-secret/token/provider/Evidence/Document/claim execution.

## Next boundary
A separately reviewed Phase 17.5-F may introduce a narrowly scoped credential-reference resolver/health qualification that can prove the externally managed reference is resolvable without persisting secret values or granting document-read authority. OAuth/token exchange, provider file reads and Evidence admission should remain separate later authority increases.

See ADR-209 and issue #410.
