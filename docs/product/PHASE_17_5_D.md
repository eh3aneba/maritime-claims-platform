# Phase 17.5-D — One-use external provider bootstrap consumption

## Goal
Consume one valid Phase 17.5-C external-provider bootstrap authorization exactly once and record the consumption as an immutable tenant-scoped execution artifact, without introducing credentials, OAuth or provider network traffic.

## Admission chain
Execution requires:
- one active Phase 17.5-A external document source profile;
- one completed integrity-valid Phase 17.5-B discovery run;
- one exact Phase 17.5-C authorization still `authorized`, unexpired and `live_connection_authorized=true`; and
- one Admin + MFA execution actor.

The authorization and all upstream lineage are revalidated immediately before consumption.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/connection-authorizations/{authorization_id}/bootstrap-executions`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/bootstrap-executions/{execution_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/bootstrap-executions/{execution_id}/receipts`

## One-use semantics
Each Phase 17.5-C authorization may be linked to only one Phase 17.5-D execution.

The execution lifecycle is exactly:
- `requested`; then
- `completed` after the Phase 17.5-C authority is terminalized.

Execution receipts are exactly `requested → completed`.

On completion:
- `authorization_consumed=true` on the Phase 17.5-D execution;
- the Phase 17.5-C authorization is terminalized through its existing `expired` state with a deterministic consumption reason containing the exact execution ID; and
- `live_connection_authorized=false` immediately.

No new Phase 17.5-C lifecycle status is introduced. The Phase 17.5-D execution artifact is the authoritative proof that the authorization was spent rather than merely timing out.

## Integrity
The execution binds and hashes:
- tenant/profile/provider identity;
- exact profile hash;
- exact discovery run ID, scope, manifest and run hashes;
- exact authorization ID, scope hash and authorization hash;
- execution request key, actor, reason and timestamp;
- the terminal hash produced when Phase 17.5-C authority is consumed; and
- completion timestamp.

Reads and replays recompute all hashes and validate both the Phase 17.5-D receipt chain and the terminalized Phase 17.5-C lineage.

Exact replay returns the same execution. Changed request facts fail closed.

## Safety boundary
Phase 17.5-D consumes governance authority only. It performs none of the following:
- credential storage;
- credential-reference storage;
- OAuth code/token exchange;
- Microsoft Graph or Google Drive network traffic;
- remote listing or file-byte reads;
- remote write/move/delete;
- provider subscriptions or sync checkpoints;
- Evidence admission;
- Document creation; or
- claim mutation.

The execution and receipt tables constrain all of those facts to false. No production provider executor is registered by this phase.

## Acceptance coverage
- real Phase 17.5-A → 17.5-B → 17.5-C → 17.5-D chain;
- successful one-use consumption;
- exact idempotent replay and changed-replay conflict;
- immediate live-authority removal;
- authorization expiry rejection;
- source-profile disable rejection;
- tenant isolation;
- receipt tamper rejection; and
- zero Claim/Document/provider execution.

## Next boundary
A separately reviewed Phase 17.5-E may introduce governed credential-reference custody for a future SharePoint / Google Drive provider client. It must not store raw secrets in application tables and must not bypass the A→B→C→D lineage. Production OAuth/token exchange, remote reads and evidence admission remain separately reviewable authority increases.

See ADR-208 and issue #408.
