# ADR-215 — Bounded transient provider-client construction and network-health qualification

## Status
Accepted for Phase 17.5-K implementation; production merge remains separately controlled.

## Context
Phase 17.5-J proves that an exact governed A→I lineage can perform one bounded identity/token acquisition while keeping credential and token material inside the token-acquirer adapter scope. That proof does not create reusable provider-client authority and does not permit remote document APIs.

The next required authority increase is narrower than remote listing: prove that the governed provider configuration can support construction of a transient authenticated provider client and one bounded non-document network/authorization health operation.

## Decision
Phase 17.5-K introduces one provider-client-health execution bound to exactly one completed Phase J execution.

The execution:

- revalidates the active/integrity-valid A→J lineage;
- locks the Phase J execution before first success;
- derives provider/client/health policy from a fixed application allowlist rather than caller input;
- invokes an empty-by-default provider-client-health adapter registry;
- permits only fixed HTTPS provider origins and allowlisted health operations;
- requires redirects to remain disabled and applies bounded timeout/response budgets;
- permits one successful execution per exact Phase J execution;
- makes exact replay idempotent and rejects changed replay/second consumption;
- persists only non-secret lineage, policy hashes, bounded health outcome, latency class and append-only receipts.

The adapter may retrieve governed credential material, acquire/use a token, construct a transient client and inspect the bounded health response entirely inside its call scope. None of those values or objects may cross the adapter contract.

## Secret/client custody boundary
The following must never be returned, persisted, logged, cached, fingerprinted or hashed into durable Phase K artifacts:

- raw credential material;
- signed assertions or authorization codes;
- access, refresh or ID tokens;
- provider response bodies;
- provider client/session objects.

Only `healthy`, a bounded failure code, latency class, provider/client/operation kind and non-secret policy hashes may cross the adapter boundary.

## Explicit exclusions
Phase K does not authorize:

- reusable provider-client/session custody outside the adapter call;
- remote SharePoint/Drive site, library, folder or file enumeration;
- remote document metadata/list/read operations;
- file download/upload;
- subscriptions or synchronization/checkpoint state;
- Document creation, Evidence admission or claim mutation;
- user/session/tenant/role authority;
- AI, coverage, causation, liability, fraud, reserve or settlement decisions.

## Consequences
The platform can prove a bounded authenticated provider-client/network path without yet gaining remote document authority. A failure produces no durable completed Phase K artifact, and later reads fail closed if the upstream lineage or receipt chain drifts.

Live remote metadata listing remains a separately reviewed later authority increase.

References: Issue #423 and Phase 17.5-K product documentation.