# Phase 17.5-I — Bounded production credential-reference resolution execution

## Goal
Resolve the exact credential reference bound by the completed Phase 17.5 A→H governance chain while keeping raw secret material inside the resolver adapter's in-memory call scope and adding no OAuth, provider-network, remote-document or claim authority.

## Admission chain
Phase I requires an integrity-valid:
- Phase 17.5-A active external document source profile;
- Phase 17.5-B discovery lineage;
- Phase 17.5-C/D connection/bootstrap authorization and execution lineage;
- Phase 17.5-E active credential-reference binding;
- Phase 17.5-F successful `resolvable` health qualification;
- Phase 17.5-G activation authorization; and
- Phase 17.5-H completed one-time activation-authorization consumption.

The operator must be Admin + current tenant MFA.

## Resolver boundary
Phase I uses a dedicated credential-resolution resolver registry. It is empty unless a resolver is explicitly registered for one of the Phase E backend kinds:
- `aws_secrets_manager`;
- `azure_key_vault`;
- `gcp_secret_manager`; or
- `hashicorp_vault`.

The application service passes the exact Phase E locator to the registered adapter. The adapter may retrieve the raw secret internally, but it returns only a non-secret `CredentialReferenceResolutionResult`. There is no `value`, `secret`, `bytes`, token or credential field in the resolver result contract.

A successful result means only that the exact governed reference was retrievable during that bounded call. The raw secret is not reusable after Phase I.

## Lifecycle
A durable successful Phase I execution uses:
- `requested → completed`.

Failures during resolution roll back the transaction and create no durable Phase I execution or receipt. This makes secret-manager outages and other bounded resolution failures retryable without fabricating successful authority.

One successful Phase I execution is allowed per Phase H execution. Exact replay is idempotent and does not invoke the resolver again. Changed replay and second consumption conflict.

## Stored facts
Phase I stores only non-secret governance facts:
- organization/profile IDs;
- Phase H activation execution ID;
- upstream authorization/health/binding IDs;
- provider kind and profile hash;
- locator hash, never raw locator namespace/name/version in the Phase I row;
- reference backend;
- Phase F health resolver kind and Phase I resolution resolver kind;
- health and Phase H execution hashes;
- request key, requester, reason and timestamps;
- Phase I scope/request/completion hashes; and
- append-only receipt hashes.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{activation_execution_id}/credential-resolution-executions`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{execution_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{execution_id}/receipts`

All endpoints require Admin + MFA. The request schema accepts only `request_key` and `reason`.

## Bounded failure codes
A resolver may return only:
- `reference_not_found`;
- `reference_unresolved`;
- `permission_denied`;
- `backend_unavailable`; or
- `resolver_rejected`.

Unexpected resolver exceptions are surfaced only as a generic credential-resolution failure. Raw exception text is not returned by Phase I.

## Safety boundary
A completed Phase I execution has:
- `credential_reference_stored=true` as inherited non-secret reference lineage;
- `activation_authorization_consumed=true` as inherited Phase H governance fact; and
- `credential_reference_resolution_performed=true` as the sole new positive Phase I execution fact.

It keeps false:
- `credential_stored`;
- `oauth_authorization_code_stored`;
- `oauth_token_exchanged`;
- `access_token_stored`;
- `refresh_token_stored`;
- `client_secret_stored`;
- `private_key_stored`;
- `provider_client_activation_authorized`;
- `provider_network_performed`;
- `remote_list_performed`;
- `remote_read_performed`;
- `remote_write_performed`;
- `remote_delete_performed`;
- `subscription_created`;
- `checkpoint_created`;
- `sync_executed`;
- `evidence_admitted`;
- `document_created`; and
- `claim_mutated`.

Resolved secret material must never appear in an API response, database row, receipt, audit metadata/details, application log, lineage hash input, cache, checkpoint, background job or telemetry.

## Acceptance coverage
The Phase I acceptance path uses one database reset and one real A→I lineage. It covers:
- explicit missing-resolver fail-closed behavior with zero I rows;
- bounded negative resolution with zero I rows;
- resolver exception sanitization, including a test exception containing a secret marker;
- strict request schema rejecting secret-like extra fields;
- tenant isolation before resolver invocation;
- successful in-memory-only resolution;
- absence of the resolved secret marker from response, persisted execution/receipt fields, audit payload and captured logs;
- exact replay without a second resolver call;
- changed replay and second request-key conflicts;
- requested/completed receipt-chain integrity;
- receipt truncation and tamper rejection;
- upstream binding disable causing completed Phase I reads to fail closed;
- unchanged Claim and Document counts; and
- all OAuth/token/provider-network/remote-document/Evidence/Document/claim authority facts remaining false.

## Next boundary
Phase 17.5-J may introduce separately governed OAuth/token acquisition. Provider-client construction/network health, live metadata listing, remote file read, synchronization, Document creation and Evidence admission remain later separately reviewed authority increases.

See ADR-213 and Issue #418.
