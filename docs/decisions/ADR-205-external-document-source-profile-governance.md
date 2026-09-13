# ADR-205: Govern external document source profiles before any provider connection

## Status
Accepted for Phase 17.5-A implementation.

## Context
The platform already supports governed email ingestion, while the remaining enterprise integration backlog includes document repositories such as Microsoft SharePoint and Google Drive. A direct jump from “provider selected” to OAuth, remote enumeration or evidence ingestion would collapse several materially different authorities into one step.

Before any provider can be connected, the system needs an immutable tenant-scoped record of which non-secret remote scope is intended, who requested it, who independently approved it, and whether that governance record remains active. That record must not itself be usable as a credential or an execution token.

## Decision
Phase 17.5-A introduces governed external document source profiles for `sharepoint` and `google_drive`.

A profile stores only normalized non-secret identifiers:

- SharePoint: `tenant_domain`, `site_id`, `library_id`;
- Google Drive: `shared_drive_id` and optional `folder_id`.

Provider configuration uses a strict whitelist. Unknown keys are rejected, which prevents token, password, client-secret, private-key and similar material from entering this custody surface.

### Four-eyes lifecycle
An Admin + MFA actor requests a profile. A different Admin + MFA actor must approve or reject it. An approved profile becomes `active`; an active profile may later be `disabled` by Admin + MFA.

`active` means only that the intended non-secret source scope has passed governance. It does **not** mean a provider connection is active.

The immutable request is SHA-256 bound to the tenant, provider, normalized configuration, requester, reason and request time. Approval/rejection/disable decisions are separately hash-bound. Every lifecycle event emits an append-only hash-chained receipt.

### Safety boundary
Database constraints keep all of these false on both profiles and receipts:

- credential storage;
- OAuth/token exchange;
- remote list/read/write/delete;
- provider subscription creation;
- synchronization execution;
- Evidence admission;
- Document creation;
- claim mutation; and
- live provider-connection authority.

Phase 17.5-A imports no provider SDK and performs no provider network call.

### Future phases
A later phase may introduce credential custody and provider-specific connection authorization. That work must bind to an exact active Phase 17.5-A profile and add its own independent authority, health and rollback controls. Phase 17.5-A cannot be treated as that authority.

## Consequences
The platform gains an auditable, tenant-isolated inventory of intended SharePoint and Google Drive source scopes without increasing remote or evidence-handling authority. Future integration work can build on a stable governance identity rather than accepting raw provider configuration at execution time.

## Verification
Release requires API-chain tests for normalization, tenant isolation, Admin+MFA access, four-eyes approval, replay, receipt integrity, secret/unknown-field rejection, disable behavior and zero remote/evidence/claim mutation.

References: #402, #400.
