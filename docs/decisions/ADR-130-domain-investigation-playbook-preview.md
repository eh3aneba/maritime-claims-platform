# ADR-130 — Governed domain investigation playbook preview

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** Claims product / engineering
- **Related:** ADR-127, ADR-128, ADR-129, Phase 16.2-A / Issue #239

## Context

Phase 16.1 introduced a governed, append-only human `ClaimDomainClassification`, allowed the current classification to appear as bounded `domain_context` inside an explicitly built Claims Intelligence snapshot, and exposed the classification workflow to handlers.

The next useful capability is domain-aware investigation support. The existing deterministic rule service, however, is not a read-only suggestion layer: evaluating claim rules can synchronize active document requirements, claim issues and requirement-driven tasks. Passing the contextual classification directly into that engine would therefore grant a classification action operational authority that Phase 16.1 intentionally withheld.

We need a useful domain-aware layer before designing any future explicit adoption/activation authority.

## Decision

We will add a separate, application-owned and versioned **domain investigation playbook registry** plus a claim-scoped read-only preview endpoint.

### Registry scope

The registry defines exactly one canonical playbook for each governed Phase 16.1 incident domain:

- Machinery Failure;
- Collision;
- Grounding;
- Fire;
- Cargo Damage;
- Pollution;
- Salvage; and
- General Average.

Each playbook contains only bounded investigation material:

- investigation tracks;
- evidence/document prompts;
- review topics; and
- selected existing Marine Registry rule IDs that may be contextually relevant.

The referenced rule IDs remain references only. The preview does not evaluate those rules.

### Deterministic versioning and integrity

The registry is versioned independently as `16.2-A.1`. A deterministic SHA-256 registry hash covers the registry version and canonical playbook payload.

Import-time validation fails closed if the registry contains duplicate incident codes or if its incident-code set differs from the governed Phase 16.1 catalog. This prevents silent domain drift.

### Claim-scoped preview

`GET /claims/{claim_id}/intelligence/domain-playbook-preview` remains behind the existing tenant-scoped claim security boundary.

If no current classification exists, the endpoint returns:

- `classification_required=true`;
- the registry version/hash and authority flags; and
- no fabricated classification context or playbook.

If a current classification exists, the endpoint resolves exactly one playbook from the classification incident code and source-links the response to:

- classification id;
- catalog version;
- classification sequence; and
- classification integrity hash.

The bounded classification context may expose canonical incident/component labels and the optional failure-mode text already held in the controlled classification record.

The human free-text **classification note is never copied into the preview or source reference**.

### Reclassification semantics

The playbook preview is a live read-only view of the latest append-only classification, not an immutable Claims Intelligence snapshot. It may therefore reflect a newly saved classification immediately.

This does not mutate, supersede or rebuild an existing Claims Intelligence snapshot. The separate Build/Refresh Intelligence authority defined in ADR-128/129 remains unchanged.

### Authority boundary

Retrieving the preview must create zero:

- `RuleEvaluationRun` rows;
- `ClaimDocumentRequirement` rows;
- `ClaimIssue` rows;
- Claim Facts;
- tasks or document requests;
- Claims Intelligence snapshots; or
- substantive claim decisions.

The preview must not determine or imply a decision on:

- coverage;
- causation;
- fault or liability;
- recoverability;
- governing law;
- legal time bars;
- reserve;
- settlement;
- payment; or
- claim closure.

Phase 16.2-A intentionally includes **no POST/apply/activate endpoint**. Any future transition from preview prompts into active requirements, tasks or rule execution requires a separately designed, explicit human-authority boundary.

## Consequences

- Handlers can immediately see domain-specific investigation prompts after classification without triggering workflow mutations.
- Reclassification changes the live preview source identity immediately while immutable Intelligence snapshots remain unchanged until separately refreshed.
- The product gains a clean architectural seam for a future explicit playbook-adoption workflow without coupling classification directly to the current rule engine.
- No database migration is required.
- Existing rules, requirement synchronization, task synchronization and Claims Intelligence build behavior remain unchanged.

## Verification

Regression coverage must prove:

1. the registry contains exactly one playbook for every governed incident code;
2. registry version/hash are deterministic;
3. an unclassified claim returns a bounded classification-required preview with zero side effects;
4. Machinery Failure returns machinery-specific evidence/investigation prompts and exact classification lineage;
5. Collision and other domains resolve their own playbooks rather than machinery defaults;
6. the human classification note is absent from the preview and source references;
7. reclassification changes preview identity immediately without creating rule runs, requirements, issues, tasks or Intelligence snapshots; and
8. cross-tenant preview access fails closed through the existing claim security boundary.

The repository's normal backend, PostgreSQL/Alembic, frontend, Docker, browser E2E, Operational Performance Smoke, Production Deployment Policy and Supply Chain Security gates remain required before merge.
