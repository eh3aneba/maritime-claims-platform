# ADR-213 — Bounded production credential-reference resolution execution

## Status
Accepted for Phase 17.5-I implementation; production merge remains separately controlled.

## Context
Phase 17.5-A through H establish a governed SharePoint/Google Drive source profile, metadata discovery, connection/bootstrap authorization and consumption, non-secret credential-reference custody, reference-health qualification, provider-client activation authorization, and one-time local activation-authorization consumption. Phase H deliberately performs no real secret retrieval, OAuth exchange, provider network call, remote document read, synchronization, Evidence admission, Document creation or claim mutation.

The next authority increase must prove that one exact governed credential reference can actually be retrieved without turning raw secret material into application state or silently granting downstream provider authority.

## Decision
Phase 17.5-I introduces one tenant-scoped credential-resolution execution per exact completed Phase H activation execution.

Admission revalidates the full A→H lineage and requires Admin + current tenant MFA. The Phase H row is locked before first resolution so two concurrent consumers cannot both create an I execution.

A dedicated credential-resolution resolver registry is empty by default. An adapter must be explicitly registered for one of the already-governed Phase E backend kinds: AWS Secrets Manager, Azure Key Vault, GCP Secret Manager or HashiCorp Vault.

The resolver interface intentionally does **not** return secret bytes or a secret string. A resolver retrieves secret material internally, determines whether the exact governed reference was successfully resolved, discards the raw material inside the adapter scope, and returns only a `CredentialReferenceResolutionResult` containing `resolved` and an optional bounded failure code. This prevents the application service, ORM, API serializer, audit layer and receipt layer from ever receiving the secret value.

Successful execution persists only non-secret lineage: Phase H execution ID/hashes, upstream IDs, provider/backend kinds, locator hash, health/resolution resolver kinds, request/completion hashes, timestamps and hash-chained receipts. Raw locator namespace/name/version fields are not copied into Phase I rows.

Failures before successful completion are retryable and create no durable Phase I row. Resolver exceptions are converted to a generic application conflict with suppressed exception chaining so raw provider exception text is not returned through the endpoint. Bounded negative result codes are restricted to `reference_not_found`, `reference_unresolved`, `permission_denied`, `backend_unavailable`, and `resolver_rejected`.

## Safety boundary
The sole new positive execution fact is `credential_reference_resolution_performed=true` on a completed Phase I execution and completed receipt. `activation_authorization_consumed=true` is inherited from the already-completed Phase H lineage and grants no new authority.

Phase I stores no credential, OAuth authorization code, access token, refresh token, client secret or private key. It performs no OAuth/token exchange, SharePoint/Microsoft Graph/Google Drive provider traffic, remote list/read/write/delete, subscription/checkpoint/synchronization operation, Evidence admission, Document creation or claim mutation.

Resolved secret material must never be returned, persisted, logged, included in audit details, hashed/fingerprinted into lineage, placed in metrics/telemetry, cached, or copied into a background job.

## Integrity and replay
One successful Phase I execution is permitted per Phase H execution. Exact replay returns the existing execution without calling the resolver again. Changed replay or a second request key conflicts. Every read revalidates Phase H and the active Phase E credential binding and validates exactly two hash-chained `requested → completed` receipts. Upstream disable/drift and receipt tamper/truncation fail closed.

## Consequences
Phase I proves bounded credential resolvability at execution time without creating reusable secret state. A later OAuth/token tranche cannot reuse a Phase I secret because no such value survives; it must obtain its own separately authorized resolution/token execution. This repetition is intentional and preserves authority separation.

## Next boundary
Phase 17.5-J may introduce a separately reviewed OAuth/token acquisition execution. Provider-client construction/network health, live remote metadata listing, remote file read, synchronization and Evidence admission remain subsequent independent authority increases.

References: Issue #418 and Phase 17.5-I product documentation.
