# Phase 17.5-C — Bounded external provider connection authorization

## Goal
Add a four-eyes governance gate between a completed read-only external-source discovery and any future SharePoint / Google Drive connection executor.

## Admission chain
A request must bind to:
- one active Phase 17.5-A external document source profile;
- one completed integrity-valid Phase 17.5-B discovery run for that exact profile;
- the exact profile, discovery scope, manifest and run hashes; and
- one Admin + MFA requester.

A different Admin + MFA actor must approve the request.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/discoveries/{run_id}/connection-authorizations`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/approve`
- `POST /api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/reject`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/receipts`

## Time and use boundary
- second-approval review window: exactly 10 minutes;
- approved connection-bootstrap authority window: exactly 10 minutes;
- execution limit recorded by this phase: exactly 1 future attempt.

The service independently recomputes both fixed TTLs from the stored request/approval timestamps; changing a deadline and merely re-hashing the record does not make the drift valid.

Expiry is fail-closed and emits an append-only terminal receipt. This phase does not itself consume the execution attempt; a future executor must enforce one-use consumption independently.

## Integrity model
The authorization stores and hashes:
- tenant/profile/provider identity;
- exact profile hash;
- discovery run id;
- discovery scope, manifest and run hashes;
- request key and reason;
- requester and review deadline;
- independent approval decision and authority deadline; and
- execution limit = 1.

Lifecycle receipts are exactly:
- `requested` while pending;
- `requested → authorized` after approval;
- `requested → rejected` after rejection;
- `requested → expired` when the review window lapses or the bound profile becomes inactive before approval; or
- `requested → authorized → expired` when approved authority lapses unused or the bound profile becomes inactive after approval.

Receipt validation cross-checks actor, timestamp, reason, lifecycle status, decision hash, live-authority fact and prior hash against the authorization record. Re-hashing a receipt with changed event facts therefore still fails closed.

Any read/approval/replay revalidates the exact upstream profile and discovery lineage. If the governed source profile has been disabled, a pending or approved authorization is reconciled to `expired` and `live_connection_authorized` is cleared before it can be treated as usable.

## Safety boundary
`live_connection_authorized=true` appears only during the approved, unexpired authorization window while the bound source remains active. It is a governance fact, not evidence that a connection exists.

The following remain false throughout Phase 17.5-C:
- credential storage;
- OAuth/token exchange;
- remote listing;
- raw remote read;
- remote write/delete;
- subscription creation;
- synchronization execution;
- Evidence admission;
- Document creation; and
- claim mutation.

No provider SDK, OAuth flow, client secret, private key, authorization code, access token or refresh token is introduced by this phase.

## Acceptance coverage
- real Phase 17.5-A → 17.5-B → 17.5-C chain;
- independent second approval;
- self-approval rejection;
- exact replay;
- source-profile disable terminalizes pending and already approved authority;
- bounded expiry and live-authority removal;
- tenant isolation;
- direct receipt tamper rejection;
- re-hashed receipt-fact drift rejection;
- re-hashed TTL-policy drift rejection; and
- zero Claim/Document/provider execution.

## Next boundary
A separately reviewed Phase 17.5-D may implement one bounded provider-connection bootstrap executor that consumes one valid, unexpired Phase 17.5-C authorization. That executor must revalidate the Phase 17.5-C artifact and its active upstream lineage immediately before any credential/provider action. Credential custody, OAuth/token exchange, production provider clients and connection-health qualification remain out of scope here.

See ADR-207 and issue #406.
