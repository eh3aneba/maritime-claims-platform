# ADR-227: Human-controlled external Evidence admission authorization

## Status
Accepted for Phase 17.5-W.

## Context
Phase 17.5-V can perform one bounded metadata-only exact-item observation against the immutable generation-3 checkpoint. It intentionally has no authority to create a local `Document`, admit Evidence, parse content, mutate a Claim, or perform object-storage work.

The next authority increase must preserve human control over whether a governed external file is allowed to cross the Evidence/Document admission boundary. Combining authorization and admission would make review, replay, revocation-by-non-consumption, and audit interpretation materially harder.

## Decision
Phase 17.5-W records an immutable Admin+MFA authorization for exactly one tenant Claim and exactly one integrity-valid Phase-V execution.

Creation succeeds only when the Phase-V execution is completed with `result_status=unchanged`, its observed projection still equals its baseline projection, and it is the latest completed generation-3 observation for the same generation-3 checkpoint at authorization time. The Claim must be active and belong to the same organization.

The authorization persists only internal UUIDs, bounded hashes, bounded metadata classes and human decision metadata. It does not persist raw provider item IDs, provider URLs, object-storage keys, credentials, tokens, or remote content.

Phase W performs no provider or object-storage I/O and creates no `Document` or Evidence. It also performs no OCR, parsing, indexing, extraction, Claim mutation, checkpoint advance, restaging or background synchronization.

The authorization is immutable. A later separately reviewed admission execution must consume it at most once and must revalidate currentness immediately before actual admission. A newer remote observation does not rewrite historical W authorization; it can only make that authorization ineligible for future consumption.

## Consequences
- Human intent is explicit and independently auditable before Evidence admission authority exists.
- Historical authorizations remain integrity-verifiable without pretending they are permanently current.
- The eventual admission phase receives a narrow single-use capability rather than general external-source authority.
- One additional control-plane step is required before an external file can become local Evidence.
