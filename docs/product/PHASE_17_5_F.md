# Phase 17.5-F — Governed external credential-reference health qualification

## Goal
Prove whether one active Phase 17.5-E credential reference is resolvable without persisting secret material and without granting SharePoint / Google Drive document authority.

## Admission chain
A qualification must bind to:
- one active Phase 17.5-A external document source profile;
- its integrity-valid Phase 17.5-B discovery lineage;
- its exact Phase 17.5-C authorization lineage;
- one completed integrity-valid Phase 17.5-D bootstrap execution;
- one active integrity-valid Phase 17.5-E credential-reference binding; and
- one Admin + MFA operator.

## Resolver contract
Phase F exposes a provider-neutral health resolver protocol.

Production starts with an empty resolver registry. No AWS Secrets Manager, Azure Key Vault, GCP Secret Manager or HashiCorp Vault production client is registered by this tranche.

A registered resolver receives only the canonical non-secret Phase E locator components and returns only:
- whether the reference is resolvable; and
- a bounded non-secret failure code when it is not.

The application service never accepts a resolved credential value from the resolver contract.

## Bounded single-use qualification
Each active Phase E binding can have at most one Phase F qualification.

Exact replay returns the existing qualification without invoking the resolver again. Changed replay conflicts. This keeps credential-reference resolution authority single-use for that governed binding.

## Stored facts
A qualification stores only:
- exact Phase E lineage hashes and binding ID;
- locator hash and credential-reference backend;
- resolver kind;
- request key/requester/reason/timestamps;
- `resolvable` or `unresolvable`;
- one bounded failure code when unresolvable;
- deterministic request/result hashes; and
- safety facts.

No raw credential, token, password, private key, resolved value or resolver exception detail is persisted.

## Receipts
A successful qualification emits exactly:
- `requested`; then
- `completed`.

The completed receipt carries status `resolvable` or `unresolvable` and `credential_reference_resolution_performed=true`.

Receipts are append-only and hash-chained. Every read revalidates the complete receipt lifecycle and upstream Phase E lineage.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/health-qualifications`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}/receipts`

All endpoints require Admin + MFA.

## Safety boundary
The only new positive execution fact is:
- `credential_reference_resolution_performed=true` for a completed health qualification.

The following remain false throughout Phase 17.5-F:
- `credential_stored`;
- `oauth_token_exchanged`;
- `provider_network_performed`;
- remote list/read/write/delete;
- subscription creation;
- synchronization execution;
- Evidence admission;
- Document creation; and
- claim mutation.

Phase F does not exchange OAuth tokens, register or activate a Microsoft Graph / Google Drive client, read remote documents, create checkpoints, or admit evidence.

## Fail-closed behavior
- missing resolver registration: 409, no qualification persisted;
- resolver exception: 409 with generic error, no secret/error detail persisted;
- inactive Phase E binding: 409;
- inactive source profile: 409;
- upstream hash drift: 409;
- receipt tamper/truncation: 409;
- cross-tenant access: 404.

## Acceptance coverage
- real A→B→C→D→E→F chain;
- active Phase E binding required;
- empty production resolver registry;
- deterministic resolvable and unresolvable test resolvers;
- exact replay without a second resolver call;
- changed replay conflict;
- no secret value in response, database, audit metadata or receipts;
- upstream binding disable/integrity drift fail closed;
- tenant isolation;
- receipt tamper rejection;
- zero OAuth/provider-document/Evidence/Document/claim execution.

## Next boundary
A separately reviewed Phase 17.5-G may introduce a bounded OAuth/token acquisition authorization and/or provider-client activation prerequisite. It must remain separate from remote document reads and Evidence admission. Any real secret-manager adapter registration should be separately reviewed and must preserve the Phase F no-persistence contract.

See ADR-210 and issue #412.
