# ADR-129 — Handler-facing claim-domain classification workspace

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** Claims product / engineering
- **Related:** ADR-127, ADR-128, Phase 16.1-C / Issue #237

## Context

Phase 16.1-A introduced a governed, versioned and append-only `ClaimDomainClassification` lineage. Phase 16.1-B allowed the current human-confirmed classification to be consumed as bounded `domain_context` only when an operator explicitly builds Claims Intelligence.

The backend capability was not yet usable from the claim workbench. The existing Claims Intelligence UI also rendered only a fixed list of item categories, so a valid `domain_context` item could exist in an immutable snapshot without being visible to the handler.

A user-facing surface is therefore required, but it must not collapse the distinction between:

1. recording human incident context; and
2. explicitly building a non-authoritative Claims Intelligence snapshot.

## Decision

We will expose claim-domain classification inside the authenticated, claim-scoped Claims Intelligence workspace with the following controls.

### Catalog-driven classification

The UI loads the canonical domain catalog from the claim-scoped API and uses it as the only source for selectable incident and machinery-component codes. The client does not invent a default incident classification.

Machinery component selection is shown only when the selected incident permits components. Failure mode remains optional and is disabled unless a compatible component is selected. Server-side validation remains authoritative and fail-closed.

### Explicit human confirmation

Creating the first classification or recording a reclassification requires:

- a human classification note meeting the API minimum length; and
- an explicit confirmation checkbox acknowledging that the classification is contextual and non-authoritative.

The client-side disabled state is a usability control only. The backend confirmation and taxonomy validation remain mandatory.

### Append-only reclassification

The UI never edits or deletes an existing classification. A change creates the next classification version through the existing append-only POST API. The current version and complete history remain visible, including classification sequence, timestamp, classifier identifier, supersession lineage and integrity hashes.

### Classification and Intelligence remain separate actions

Saving a classification refreshes only the classification/current/history state. It must not call the Claims Intelligence build endpoint.

The UI explicitly tells the handler that Claims Intelligence was not rebuilt automatically and that Build/Refresh Intelligence must be invoked separately if the new classification should be reflected in a snapshot.

This intentional separation allows a previously built immutable snapshot to remain visible until the handler requests another build.

### Bounded note visibility

The free-text human classification note is visible within the classification workspace and history because it is part of the controlled human record.

The note is not copied into the generated `domain_context` Intelligence item or its source refs. Claims Intelligence receives only the bounded classification identity, canonical codes/context and integrity lineage defined by ADR-128.

### Render `domain_context`

The Claims Intelligence UI adds `domain_context` to its governed section order. It renders only when the current immutable snapshot actually contains that category. The UI does not synthesize a domain-context item directly from the classification panel.

### Authority boundary

Neither the classification UI nor the rendered `domain_context` item may imply or automatically create a decision about:

- coverage;
- causation;
- fault or liability;
- fraud;
- recoverability;
- governing law;
- legal time bars;
- reserves;
- settlement;
- payment; or
- claim closure.

Saving classification must not automatically execute rules, build Intelligence, create or mutate Claim Facts, create tasks/document requests, or mutate claim type/status.

## Consequences

- There can intentionally be a short-lived difference between the latest classification version and the classification reflected in the latest Intelligence snapshot. The UI makes this explicit instead of hiding it.
- Classification history remains auditable and append-only.
- The Intelligence snapshot remains content-addressed and immutable.
- No database migration is required for Phase 16.1-C.
- The handler now has a complete UI path for the Phase 16.1-A/B capability without broadening automated claim authority.

## Verification

The normal repository gates remain required: backend test suite, PostgreSQL/Alembic preflight, frontend typecheck/build, Docker validation, MT ORION browser E2E, Operational Performance Smoke, Production Deployment Policy and Supply Chain Security.

A focused browser regression must additionally prove that:

1. no classification is fabricated for an unclassified claim;
2. component/failure-mode controls follow the canonical incident catalog;
3. explicit confirmation is required before save;
4. saving classification does not build Intelligence;
5. after an explicit build, `domain_context` becomes visible and source-linked;
6. the free-text classification note is absent from the rendered Intelligence item;
7. reclassification creates the next history version while the previous immutable snapshot remains unchanged until Refresh Intelligence; and
8. the next explicit refresh reflects the newer classification.
