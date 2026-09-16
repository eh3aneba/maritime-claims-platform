# Phase 17.5-J — Bounded OAuth/token acquisition execution

## Goal

Perform one approved identity/token-endpoint acquisition for the exact completed Phase 17.5-I credential-resolution lineage while keeping every raw credential, assertion and acquired token inside the token-acquisition adapter call.

Phase J proves only that the bounded token acquisition happened. It does not create reusable provider authority.

## Preconditions

A Phase J execution requires the same organization and source profile to retain an active, integrity-valid A→I lineage. The exact Phase I row is locked before first Phase J execution and is unique-consumed by Phase J.

## Provider policy

Callers cannot provide token endpoints, audiences, flows, credentials, assertions or tokens.

The service derives a fixed non-secret policy:

| Provider | Token flow | Approved identity origin | Governed variation |
| --- | --- | --- | --- |
| SharePoint | `client_credentials` | `https://login.microsoftonline.com` | exact approved `tenant_domain` only |
| Google Drive | `jwt_bearer` | `https://oauth2.googleapis.com` | no dynamic token host |

SharePoint tenant-domain syntax is revalidated before URL construction. The policy requires HTTPS, prohibits redirect following and carries bounded connect/read/total timeout and response-size limits.

Only an explicitly registered adapter whose provider, flow and endpoint origin exactly match that policy may run. The registry is empty by default.

## Adapter boundary

The adapter receives the bound credential-reference locator and derived provider/token-flow policy. It may resolve the credential and perform the token request internally, but it must destroy all secret-bearing values before returning.

The only allowed return shape is a bounded non-secret result: acquired yes/no, a bounded failure code when not acquired, and a bounded expiry class when acquired. There is no adapter return field for a credential, client secret, private key, assertion, authorization code, access token, refresh token, ID token or provider response body.

## Persisted proof

A successful execution stores only organization/profile and exact upstream IDs; provider, credential backend and resolver kinds; Phase I scope/request/completion hashes; token-flow and acquirer kinds; a deterministic endpoint-policy hash; request/scope/completion hashes; `result_status=acquired`; bounded `expiry_class`; timestamps; and append-only receipt hashes.

The raw endpoint URL, tenant hint, credential-reference namespace/name/version, credentials and tokens are not exposed in the Phase J API shape.

## Safety state

On completion, `credential_reference_stored`, `credential_reference_resolution_performed`, `activation_authorization_consumed`, `token_acquisition_performed`, `oauth_token_exchanged` and `token_endpoint_network_performed` are true.

Credential/token/code/key storage, reusable provider-client construction, provider data-API traffic, remote list/read/write/delete, subscriptions, checkpoints, synchronization, Evidence admission, Document creation and claim mutation remain false and database-constrained false.

## API

Organization administrators with the existing MFA assurance requirement may execute:

`POST /api/v1/external-document-sources/profiles/{profile_id}/credential-resolution-executions/{credential_resolution_execution_id}/token-acquisition-executions`

The request accepts only `request_key` and `reason`.

Tenant-scoped reads are available at:

`GET /api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{execution_id}`

and:

`GET /api/v1/external-document-sources/profiles/{profile_id}/token-acquisition-executions/{execution_id}/receipts`

Unknown and secret-like request fields are rejected by the strict schema.

## Replay and failure behavior

- Missing token acquirer: fail closed.
- Unsupported provider/flow/origin: fail before adapter execution.
- Provider rejection, timeout, malformed response or oversized response: bounded failure and transaction rollback.
- Adapter exception: sanitized `Token acquisition failed`; adapter exception text is not returned.
- Wrong tenant: rejected before adapter invocation.
- Successful exact replay: returns the same record with no second token exchange.
- Changed replay or second request key for the same Phase I execution: conflict.
- Receipt tampering or upstream A→I drift: read fails closed.

Failed acquisition attempts leave no durable Phase J execution or receipt.

## Still not allowed

Phase J cannot return/persist access, refresh or ID tokens; persist raw credential material/assertions/codes; build/cache a reusable provider client; call Microsoft Graph, SharePoint or Google Drive data APIs; list/read remote content; synchronize/checkpoint; create Documents/Evidence; or mutate claims.

Those remain later separately reviewed authority increases.

See ADR-214 and Issue #421.
