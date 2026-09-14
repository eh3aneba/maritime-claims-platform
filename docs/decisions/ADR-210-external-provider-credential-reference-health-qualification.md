# ADR-210: Qualify external credential-reference resolvability without provider authority

## Status
Accepted for Phase 17.5-F implementation.

## Context
Phase 17.5-E stores only governed, canonical non-secret locator metadata for an externally managed credential. It deliberately does not resolve that locator or grant provider-document authority.

Before any future OAuth/token or SharePoint / Google Drive client activation is considered, the platform needs a bounded way to prove that an active credential reference is resolvable while keeping the resolved value out of application persistence, API responses, audit metadata and receipts.

## Decision
Phase 17.5-F introduces one bounded credential-reference health qualification per active Phase 17.5-E binding.

### Admission chain
A qualification requires the exact integrity-valid A→B→C→D→E lineage and an active Phase E binding. The request requires Admin + MFA.

Each active Phase E binding can be health-qualified once. An exact replay returns the existing qualification without invoking the resolver again. A changed replay conflicts. A new resolution attempt therefore requires a newly governed upstream binding rather than silently widening the existing authority.

### Resolver boundary
The application exposes a provider-neutral resolver protocol and an in-process registry keyed by credential-reference backend. The production registry is empty by default. Deterministic resolvers may be registered by tests.

A resolver receives only canonical locator components already governed by Phase E and returns only:
- `resolvable: bool`; and
- when not resolvable, one bounded non-secret failure code.

The service contract does not accept a resolved credential value from the resolver. Resolved values must never be returned by API, persisted, hashed, logged, placed in audit metadata or written into receipts.

Supported bounded failure codes are:
- `reference_not_found`;
- `reference_unresolved`;
- `permission_denied`;
- `backend_unavailable`; and
- `resolver_rejected`.

Resolver absence fails closed before any health record is created. Resolver exceptions also fail closed with a generic error that does not persist exception detail.

### Qualification record
The completed qualification binds:
- tenant/profile/provider identity and exact profile hash;
- exact Phase E binding ID;
- Phase E scope, request and approval hashes;
- exact locator hash and reference backend;
- resolver kind;
- request key, requester, reason and timestamp;
- checked-at timestamp;
- `resolvable` or `unresolvable` outcome;
- bounded failure code when unresolvable; and
- deterministic request/result hashes.

The only new positive execution fact is `credential_reference_resolution_performed=true` on the completed qualification and completed receipt. It means only that the governed credential reference was health-qualified. It does not grant provider-document authority.

### Receipts
Every successful qualification emits exactly two append-only hash-chained receipts:
- `requested` with resolution not yet performed; and
- `completed` with resolution performed and status `resolvable` or `unresolvable`.

Receipt validation cross-checks sequence, actor, time, reason, status, decision hash, prior hash and every safety fact against the qualification source record.

### Upstream fail-closed behavior
Every qualification read and receipt read revalidates the active Phase E binding and its complete upstream lineage. If the source profile or Phase E binding is no longer active, or if any upstream hash drifts, Phase F fails closed.

## Safety boundary
Phase 17.5-F performs none of the following:
- credential/password/client-secret/private-key persistence;
- OAuth authorization-code/access-token/refresh-token exchange or persistence;
- SharePoint, Microsoft Graph or Google Drive client/network activity;
- remote list/read/write/move/delete;
- provider subscription or synchronization state creation;
- Evidence admission;
- Document creation; or
- claim mutation.

Database constraints keep these authority facts false.

## Consequences
The platform can prove a governed external credential reference is currently resolvable without taking custody of credential material and without combining secret resolution with provider-document authority.

OAuth/token exchange and provider-client activation remain separate future authority increases. Remote document reads and Evidence admission remain later phases.

## Verification
Release requires:
- real A→B→C→D→E→F lineage;
- active Phase E binding requirement;
- resolver-unavailable fail-closed behavior;
- deterministic resolvable and unresolvable outcomes;
- one resolution attempt per binding with exact replay idempotency;
- no secret value in response, persistence, audit metadata or receipts;
- tenant isolation;
- upstream disable/integrity drift fail closed;
- receipt-tamper rejection; and
- zero OAuth/provider-document/Evidence/Document/claim execution.

References: #412, ADR-209.
