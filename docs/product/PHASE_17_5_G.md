# Phase 17.5-G — Governed provider-client activation authorization

## Goal
Authorize one later bounded provider-client activation from an exact successful Phase 17.5-F health qualification, without performing credential resolution, OAuth/token exchange, provider network traffic, remote document access or Evidence admission.

## Admission chain
A Phase G authorization must bind to:
- one active Phase 17.5-A source profile;
- its integrity-valid Phase 17.5-B discovery lineage;
- its exact Phase 17.5-C authorization lineage;
- one completed integrity-valid Phase 17.5-D bootstrap execution;
- one active integrity-valid Phase 17.5-E credential-reference binding;
- one completed integrity-valid Phase 17.5-F qualification with `result_status=resolvable`; and
- an Admin + MFA requester plus an independent Admin + MFA second approver.

## Lifecycle
- `pending_second_approval`;
- `authorized`;
- `rejected`; or
- `expired`.

The request review TTL is 10 minutes. An approved authorization is valid for 10 minutes. `execution_limit=1`.

Exact replay returns the existing authorization. A materially changed replay conflicts.

## Stored facts
Only non-secret lineage and governance facts are stored:
- exact Phase F qualification ID and hashes;
- exact Phase E binding hashes;
- provider kind, reference backend, resolver kind and locator hash;
- request key, requester, reasons and timestamps;
- four-eyes approval facts;
- execution limit;
- deterministic request/authorization/terminal hashes; and
- append-only receipt hashes.

No raw credential, OAuth code, token, secret or private key is stored.

## Receipts
Receipt lifecycle is exactly one of:
- `requested`;
- `requested → authorized`;
- `requested → rejected`;
- `requested → expired`; or
- `requested → authorized → expired`.

Receipts are append-only and hash-chained.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/credential-reference-health-qualifications/{qualification_id}/provider-client-activation-authorizations`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/approve`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/reject`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/receipts`

All endpoints require Admin + MFA.

## Safety boundary
The only new positive governance fact is:
- `provider_client_activation_authorized=true` while the authorization is `authorized`.

The Phase G action itself keeps false:
- credential-reference resolution;
- raw credential storage;
- OAuth authorization-code storage;
- OAuth token exchange;
- access-token storage;
- refresh-token storage;
- client-secret storage;
- private-key storage;
- provider network activity;
- remote list/read/write/delete;
- subscription creation;
- checkpoint creation;
- synchronization execution;
- Evidence admission;
- Document creation; and
- claim mutation.

## Fail-closed behavior
- Phase F result is not `resolvable`: 409;
- upstream Phase E binding/profile invalid or disabled: 409;
- lineage/hash drift: 409;
- receipt tamper or truncation: 409;
- requester self-approval: 409;
- cross-tenant access: 404;
- review or authorization TTL expired: authorization becomes terminal `expired` and the live authorization flag is cleared.

## Acceptance coverage
The Phase G acceptance path uses one database reset and covers:
- real A→B→C→D→E→F→G lineage;
- tenant isolation;
- exact replay and changed replay conflict;
- self-approval rejection and independent second approval;
- all OAuth/provider/Evidence/Document/claim flags remaining false;
- append-only receipt chain;
- receipt tamper rejection;
- approved authorization expiry;
- rejection of an `unresolvable` Phase F qualification using a second C→D→E→F chain on the same governed profile/discovery; and
- upstream credential-binding disable causing Phase G reads to fail closed.

## Next boundary
A separately reviewed Phase 17.5-H may consume one exact unexpired Phase G authorization into a bounded provider-client activation execution. Phase H must not silently add remote document reads or Evidence admission. Any OAuth/token acquisition or real provider-network step must remain explicit, independently bounded and auditable.

See ADR-211 and issue #414.
