# Phase 12I — Signed content-free AI governance webhooks

## Goal

Phase 12I extends the Phase 12H AI Operations governance plane with an outbound-only enterprise integration surface. Authorized tenant administrators can configure HTTPS webhook destinations and selected content-free AI governance events are delivered asynchronously with HMAC signatures, replay metadata, idempotency keys and a bounded retry/dead-letter lifecycle.

## Permanent authority boundary

This phase does **not** widen AI authority. It does not authorize new models, providers or document classes and it does not permit Restricted external processing. It does not make coverage, liability, causation, recoverability, reserve, settlement, payment or legal-right decisions and it does not promote ClaimFacts.

The integration is outbound-only. No webhook or SIEM consumer can send commands back into MCRI to pause/revoke authorizations, trigger kill switches, alter claims or perform remediation.

## Content-free envelope

Outbound payloads are produced only from the existing Phase 12H operator read model. An explicit serializer allowlist includes governance identifiers, hashes, workflow/status/failure/fallback/review metadata, provider/model/bundle identifiers and safe usage/latency/cost counters.

The payload never includes raw claim/document text, prompts, questions, retrieved passages, source-unit lists, provider responses or synthesized answer text. Each envelope records `content_free=true`, `raw_claim_or_model_content_included=false` and `inbound_command=false`.

## Destination and secret model

Destinations are tenant-scoped and admin-managed. HTTPS is mandatory. Loopback, local and literal private addresses are rejected at configuration time. The worker resolves the hostname again immediately before an actual network call and rejects any non-global result, reducing DNS-rebinding risk. Redirect following is disabled.

Raw signing secrets are never stored in the database. MCRI persists a random non-secret salt plus a key version and derives the HMAC key from the application master secret and destination identity. The derived secret is shown exactly once on create or rotation. Rotation retains the prior derivation salt/version for a short bounded transition window so already-queued deliveries can complete safely.

## Delivery lifecycle

The isolated governance webhook worker:

1. recomputes Phase 12H content-free events;
2. creates an idempotent delivery row for each enabled destination/event revision;
3. claims due rows with database locking;
4. signs the canonical JSON body;
5. POSTs without following redirects;
6. marks success or records only sanitized failure class/HTTP status;
7. retries with bounded exponential backoff and deterministic jitter;
8. moves exhausted deliveries to dead-letter state for human action.

Webhook failure never blocks the originating claim, document-processing or AI workflow.

## Signature contract

Each request carries:

- `X-MCRI-Webhook-Id`
- `X-MCRI-Webhook-Idempotency-Key`
- `X-MCRI-Webhook-Timestamp`
- `X-MCRI-Webhook-Signature: v1=<hex>`
- `X-MCRI-Webhook-Secret-Version`
- `X-MCRI-Webhook-Envelope-Version`
- `X-MCRI-Webhook-Content-Free: true`

The signature is HMAC-SHA256 over `timestamp.event_id.<canonical-body>`. Receivers should reject stale timestamps outside their replay window and deduplicate on the webhook ID/idempotency key.

## Operator experience

`/ai-integrations` provides:

- destination and delivery KPI cards;
- destination registration and enabled event categories;
- one-time signing secret disclosure;
- enable/disable, rotate and synthetic test actions;
- recent content-free delivery status;
- safe HTTP/error diagnostics and payload hash;
- explicit human retry for failed/dead-letter rows.

Claims managers can observe the integration state. Destination mutations and retry/rotation actions require an admin role.

## Validation

Phase 12I must pass exact-head backend tests, PostgreSQL migration chain, frontend typecheck/build, dependency-lock check, Compose validation, design-partner browser E2E and Supply Chain Security before integration. A fresh explicit merge authorization is required after the final head is green.
