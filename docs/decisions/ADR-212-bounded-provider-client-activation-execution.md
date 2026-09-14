# ADR-212 — Bounded provider-client activation execution consumption

## Status
Accepted for Phase 17.5-H implementation; production merge remains separately controlled.

## Context
Phase 17.5-G can grant one short-lived, four-eyes provider-client activation authorization from an exact successful Phase 17.5-F credential-reference health qualification. A later phase needs to consume that authority exactly once without silently turning local governance into credential, OAuth, provider-network, remote-document or Evidence authority.

## Decision
Phase 17.5-H introduces one local activation execution per exact Phase 17.5-G authorization.

The execution:
- requires the exact integrity-valid A→B→C→D→E→F→G lineage;
- requires G to be `authorized`, unexpired and `execution_limit=1` at the instant of consumption;
- acquires a row lock on G before first consumption;
- records `requested → completed` append-only hash-chained receipts;
- atomically terminalizes G using its existing terminal `expired` lifecycle with a consumption-specific reason bound to the H execution ID;
- stores the resulting G terminal hash in H;
- sets only `activation_authorization_consumed=true` at H completion; and
- treats exact replay as idempotent while materially changed replay conflicts.

The use of G's `expired` terminal status for consumption does not mean the authorization naturally timed out. The terminal reason and terminal hash distinguish a Phase H consumption from unused expiry, and H integrity requires that exact consumption lineage.

## Safety boundary
Phase H performs no credential-reference resolution and stores no raw credential, OAuth authorization code, token, client secret or private key. It performs no provider network traffic, remote list/read/write/delete, subscription, checkpoint or synchronization. It admits no Evidence, creates no Document and mutates no claim.

`provider_client_activation_authorized` is false on all H execution and receipt rows. `activation_authorization_consumed=true` means only that the local Phase G governance grant was terminally consumed; it is not proof of provider connectivity and grants no document-read authority.

## Concurrency and replay
The Phase G authorization row is locked before consumption and the H table has a unique authorization constraint. After acquiring the lock H rechecks whether another execution already exists. Therefore concurrent exact requests serialize into one execution, while a changed competing request fails closed.

## Integrity
H persists exact non-secret lineage hashes from G/F/E, the G authorization hash and original expiry, the G terminal hash created at consumption, request/completion hashes and a two-receipt hash chain. Reads revalidate both H and the upstream G→F→E lineage and fail closed on tamper, truncation or upstream invalidation.

## Consequences
Phase H creates no production provider client or adapter. A future phase may only introduce credential resolution, OAuth/token acquisition, provider-client construction or provider-network traffic through a separately reviewed authority increase. Remote document access and Evidence admission remain later boundaries.

See issue #416 and `docs/product/PHASE_17_5_H.md`.
