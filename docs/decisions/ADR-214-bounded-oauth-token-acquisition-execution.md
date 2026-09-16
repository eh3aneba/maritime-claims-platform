# ADR-214 — Bounded OAuth/token acquisition execution

## Status

Accepted for Phase 17.5-J implementation; production merge remains separately controlled.

## Context

Phase 17.5-I proves that one exact governed credential reference can be resolved inside a bounded adapter call without returning or persisting raw credential material. It deliberately leaves no reusable secret or token custody behind.

The next authority increase must prove that the exact active A→I lineage can perform one approved identity/token-endpoint exchange without turning the application service into a secret store, token cache, reusable provider client or provider data-plane client.

## Decision

Phase 17.5-J introduces a one-success-per-Phase-I token-acquisition execution.

The service:

- locks and revalidates the exact completed Phase I execution before first execution;
- revalidates the full upstream A→I integrity chain on every later read;
- derives provider/token-flow policy from the governed source profile rather than accepting caller-supplied endpoints, audiences or flows;
- keeps the token-acquirer registry empty by default and fails closed unless an explicitly registered provider/flow adapter exists;
- permits SharePoint `client_credentials` only at the Microsoft identity HTTPS origin, with the exact governed tenant domain;
- permits Google Drive `jwt_bearer` only at the fixed Google OAuth HTTPS origin;
- fixes bounded connect/read/total timeout budgets, response-size limit and `allow_redirects=false` in the adapter policy;
- receives only a bounded non-secret acquired/failure result and expiry class from the adapter;
- persists only non-secret lineage IDs/hashes, provider/backend/resolver/token-flow/acquirer kinds, endpoint-policy hash, request/completion hashes, bounded outcome metadata and append-only receipt hashes;
- makes exact replay idempotent and rejects changed replay or second consumption.

Phase I does not cache raw credential material. The Phase J adapter therefore owns the atomic secret boundary: it may resolve the bound credential reference and construct a provider assertion/token request internally, but raw credential material, signed assertions, authorization codes, access tokens, refresh tokens, ID tokens and provider response bodies must be discarded before the adapter returns.

## Endpoint and drift control

No Phase J request field can supply an endpoint, tenant, audience, client identifier, assertion, credential or token. The service derives the endpoint policy from the active source profile and hashes that policy into Phase J lineage. Registration rejects an adapter whose provider, flow or HTTPS endpoint origin differs from the approved provider policy. SharePoint tenant-domain syntax is revalidated before interpolation into the fixed Microsoft identity URL shape. Redirects are prohibited.

## Secret-custody boundary

Secret-bearing values must never appear in API requests/responses, database rows, receipts, audit payloads/details, caller-visible exceptions, application logs, hashes/fingerprints/metrics, background state, checkpoints or reusable clients. The adapter result type intentionally has no field capable of carrying a token, assertion, authorization code or credential value.

## Positive authority

The only new authority is proof that one approved token acquisition happened for the exact completed Phase I lineage. A completed Phase J row may record `token_acquisition_performed=true`, `oauth_token_exchanged=true`, `token_endpoint_network_performed=true`, `result_status=acquired` and a bounded expiry class.

All secret-storage and downstream provider-data fields remain database-constrained false.

## Explicit exclusions

Phase J does not persist or return credentials/tokens, create a token cache or reusable provider client, call Microsoft Graph/SharePoint/Google Drive data APIs, list/read remote files, create synchronization/subscription/checkpoint state, create Documents, admit Evidence, mutate claims, grant application identity/tenant/role authority, or make AI/coverage/causation/liability/fraud/reserve/settlement decisions.

Provider-client construction/network health and every remote-data authority increase remain separate review tranches.

## Failure and replay semantics

Missing adapters, unsupported provider/flow/origin combinations, invalid governed endpoint inputs, bounded provider failures, timeout/malformed/oversized-response outcomes and adapter exceptions fail closed. The router rolls the transaction back, so failed attempts leave no durable Phase J execution or receipt.

One completed Phase J execution is unique per Phase I execution. Exact replay returns the existing integrity-validated record without invoking the adapter again. Changed replay and second consumption fail closed.

References: Issue #421, ADR-213 and Phase 17.5-J product documentation.
