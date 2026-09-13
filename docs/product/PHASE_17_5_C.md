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
- second-approval review window: 10 minutes;
- approved connection-bootstrap authority window: 10 minutes;
- execution limit recorded by this phase: exactly 1 future attempt.

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
- `requested → expired` when the review window lapses; or
- `requested → authorized → expired` when approved authority lapses unused.

Reads recompute the complete lifecycle and fail closed on drift or tampering.

## Safety boundary
`live_connection_authorized=true` appears only during the approved, unexpired authorization window. It is a governance fact, not evidence that a connection exists.

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
- source-profile disable blocks approval;
- bounded expiry and live-authority removal;
- tenant isolation;
- receipt tamper rejection; and
- zero Claim/Document/provider execution.

## Next boundary
A separately reviewed Phase 17.5-D may implement one bounded provider-connection bootstrap executor that consumes one valid, unexpired Phase 17.5-C authorization. Credential custody, OAuth/token exchange, production provider clients and connection-health qualification remain out of scope here.

See ADR-207 and issue #406.
