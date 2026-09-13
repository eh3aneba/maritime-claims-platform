# ADR-207: Authorize external provider connection bootstrap before credential execution

## Status
Accepted for Phase 17.5-C implementation.

## Context
Phase 17.5-A governs the intended non-secret SharePoint / Google Drive source scope. Phase 17.5-B can record metadata-only discovery through a separately registered adapter, but deliberately grants no live provider-connection authority and persists no credentials.

The next authority increase must not jump directly from a discovered source to OAuth/token exchange. A separately reviewable governance artifact is required to answer a narrower question: may one future executor attempt one provider-connection bootstrap against this exact governed and discovered source?

## Decision
Phase 17.5-C introduces a short-lived, tenant-scoped provider connection-bootstrap authorization.

Admission requires:
- one exact active Phase 17.5-A source profile;
- one exact integrity-valid completed Phase 17.5-B discovery run for that profile;
- Admin + MFA requester;
- an independent Admin + MFA second approver; and
- an idempotency request key and stated reason.

The authorization binds the profile hash, discovery scope hash, manifest hash, run hash, requester, approval facts and a single future execution limit into deterministic SHA-256 lineage.

### Lifecycle
The lifecycle is `pending_second_approval → authorized` or `rejected`. A pending request expires after ten minutes if not approved. An approved authorization expires after ten minutes if unused.

Every transition emits an append-only hash-chained receipt. Exact replay is idempotent; changed replay conflicts. Receipt truncation, reordering, hash drift or bound profile/discovery drift fails closed.

### Meaning of live_connection_authorized
For the first time in the 17.5 series, a valid `authorized` artifact records `live_connection_authorized=true`.

That flag means only that one later, separately implemented and separately reviewed executor may consume this authorization before expiry. It does not mean a provider connection exists and it does not contain any credential material.

### Safety boundary
Phase 17.5-C performs none of the following:
- credential, credential-reference, authorization-code, access-token or refresh-token storage;
- OAuth/token exchange;
- Microsoft Graph or Google Drive network traffic;
- remote metadata list, file read, write, move or delete;
- provider subscription or synchronization checkpoint creation;
- Evidence admission;
- Document creation; or
- claim mutation.

Database constraints keep every execution flag false. Only the temporary `live_connection_authorized` governance fact may become true while status is `authorized`.

## Consequences
The platform gains a cryptographically bound four-eyes gate between governed discovery and any future credential/network executor. A future Phase 17.5-D may consume exactly one valid, unexpired 17.5-C authorization, but it must independently define credential custody, token handling, provider-client boundaries, rollback and health controls.

## Verification
Release requires real-chain tests covering profile → discovery → authorization request → independent approval, self-approval rejection, replay, tenant isolation, expiry, source-profile disable drift, receipt tamper rejection and zero provider/evidence/document/claim execution.

References: #406, #404, ADR-205, ADR-206.
