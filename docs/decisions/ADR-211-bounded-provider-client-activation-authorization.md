# ADR-211 — Bound provider-client activation behind a separate four-eyes authorization

## Status
Accepted for Phase 17.5-G implementation.

## Context
Phase 17.5-F can prove that one governed external credential reference is resolvable without persisting secret material or granting provider document authority. The next authority increase must not collapse credential health, provider-client activation, OAuth/token acquisition, remote document access and Evidence admission into one step.

## Decision
Phase 17.5-G introduces a separate, short-lived authorization for one later provider-client activation execution.

The authorization is admitted only from an integrity-valid Phase F qualification whose result is `resolvable`. It binds the exact A→F lineage hashes, requires Admin + MFA for the requester, and requires an independent Admin + MFA second approver.

Lifecycle:
- `pending_second_approval`;
- `authorized`;
- `rejected`; or
- `expired`.

The review window is 10 minutes. An approved authorization is valid for 10 minutes and has `execution_limit=1`.

The sole new positive governance fact is `provider_client_activation_authorized=true` while status is `authorized`.

## Explicit non-authority
Phase G does not:
- resolve a credential reference;
- persist a raw credential, password, client secret, private key, access token or refresh token;
- store an OAuth authorization code;
- exchange an OAuth token;
- instantiate or call Microsoft Graph / SharePoint / Google Drive over the network;
- list, read, write or delete remote files;
- create subscriptions, checkpoints or sync state;
- admit Evidence;
- create Documents; or
- mutate claims.

All those safety facts are persisted as false and protected by database checks and hash-chained receipts.

## Integrity and replay
Every read revalidates the exact successful Phase F result and its upstream Phase E binding. One Phase F qualification may back at most one Phase G authorization. Exact request replay is idempotent; changed replay conflicts. Receipt truncation, tamper, lineage drift, tenant mismatch or upstream invalidation fail closed.

## Consequences
Provider-client activation is now explicitly reviewable before any live execution authority exists. A later Phase 17.5-H may consume one exact unexpired Phase G authorization, but OAuth/token acquisition and provider network execution remain separately reviewed authority increases. Remote document reads and Evidence admission remain later phases.

See issue #414 and `docs/product/PHASE_17_5_G.md`.
