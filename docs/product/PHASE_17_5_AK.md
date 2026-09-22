# Phase 17.5-AK — SharePoint / Google Drive integration closure

## Goal
Prove the complete recurring external-Evidence loop using the existing A→AJ authority chain and a minimum operator surface, without creating new provider, Evidence, processing, AI or claim authority.

## Runtime provider wiring
The live adapter bundle supports:
- SharePoint / Microsoft Graph with Azure Key Vault credential references;
- Google Drive with GCP Secret Manager credential references;
- transient OAuth acquisition;
- bounded provider health;
- bounded metadata listing;
- exact-item metadata and exact content reads;
- stable provider item/version identity;
- bounded SharePoint one-hop HTTPS content redirect;
- no Google Drive redirects;
- no provider write/delete methods.

Enable only through:
`EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED=true`

The flag registers adapters; it does not create profiles or authorize any execution.

## Operator read model
`GET /api/v1/external-document-sources/operator-overview`

Admin + current MFA only. The response composes existing durable facts:
- profile status and latest provider health;
- active Evidence families;
- recurring schedule and next due time;
- latest unchanged/changed/missing observation;
- unresolved changed/missing handoff;
- latest human review decision;
- AG review, AH exact refresh/staging, AI admission-authorization and AJ admission state;
- canonical current N/N+1 version;
- exact-current-document Phase-Z release requirement.

The read model is non-authoritative and performs no mutation.

## Operator UI
`/external-evidence` presents the same state in the protected application shell, renders current + historical version lineage, exposes filters for human review and Phase-Z-required families, and provides separate governed controls for AG review, AH exact refresh/staging, AI admission authorization and AJ canonical N+1 admission. Each mutation requires an explicit human audit reason of at least 20 characters and its own request key; there is deliberately no one-click sync/admit path.

## Security invariants
- provider writes/deletes: prohibited;
- raw credentials/tokens/provider response bodies: transient only;
- changed provider content: never automatically admitted;
- missing provider content: never automatically deletes canonical Evidence;
- AG, AH, AI, AJ and Phase-Z: separate;
- AJ: no processing release inheritance;
- external AI: independently governed;
- tenant isolation + current MFA: preserved.

## Version identity
SharePoint uses a SHA-256 projection of the provider eTag. Google Drive uses a SHA-256 projection of the Drive file version and falls back to checksum/modified-time identity only when the version field is unavailable. Exact content read re-reads exact-item metadata and returns the same bounded version hash for application-level drift checks.

## No migration
AK uses existing durable tables. The operator surface is derived at request time.

## Validation required before merge
- SharePoint live-adapter contract;
- Google Drive live-adapter contract;
- unchanged / changed / missing recurring paths;
- provider auth/rate/transient failures;
- restart/replay/idempotency;
- duplicate tick/dispatch safety;
- stale review/refresh/admission paths;
- exactly one canonical current version after AJ;
- old versions remain historical;
- Phase-Z required for the exact new current document;
- zero provider write/delete;
- zero secret/token leakage;
- zero external-AI execution from this chain;
- browser E2E proves AG → AH → AI → AJ as four distinct mutations and preserves N/N+1 lineage;\n- frontend build/lint/tests;
- full backend, Postgres concurrency, deployment-policy, performance and supply-chain gates on exact PR head.
