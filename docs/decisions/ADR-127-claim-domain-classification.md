# ADR-127: Governed Claim Domain Classification

## Status
Accepted for Phase 16.1-A.

## Context
The platform already has mature, source-linked Claim Intelligence, Technical Review, marine rules, Evidence Matrix, Claim Facts, Chronology and Policy Intelligence. Those capabilities are intentionally non-authoritative and preserve human decision authority.

The remaining domain gap is different: `ClaimType` currently represents the product/workflow dimension (for example Hull & Machinery), but there is no canonical, versioned marine-incident classification dimension for contexts such as machinery failure, collision, grounding, fire, cargo damage, pollution, salvage or General Average.

Using `ClaimType` for both concepts would conflate workflow routing with casualty context. Creating new duplicate rule, evidence-requirement or intelligence tables would also fragment the existing architecture.

## Decision
### 1. Keep ClaimType and incident domain separate
`ClaimType` remains unchanged. Phase 16.1-A adds `ClaimDomainClassification` as a separate claim-scoped context lineage.

### 2. Use a versioned application-owned catalog
The initial marine domain catalog is deterministic code, versioned as `16.1-A.1`. It contains bounded incident and machinery-component codes plus contextual references to existing rule IDs where those links are already supported.

Catalog entries are not policy interpretations, legal conclusions or coverage decisions.

### 3. Classification is an explicit human action
A signed-in claim user must submit explicit confirmation and a meaningful human note. The service validates the incident/component relationship against the governed catalog before recording it.

The classification record is append-only. A later classification creates a new sequence number, points to the superseded record and cryptographically chains the previous/current classification hashes. Existing classification rows are not edited in place.

### 4. Tenant and integrity boundaries remain mandatory
All catalog/classification endpoints are claim-scoped and pass through the existing tenant claim lookup. Sequence allocation is serialized by locking the claim row before reading the current classification.

The audit event records bounded operational metadata but excludes the free-text classification note and integrity hashes.

### 5. Classification has no automatic decision authority
Creating or changing a domain classification does not automatically:
- build or mutate Claim Intelligence;
- execute marine rules;
- create or revise Claim Facts;
- create tasks or document requests;
- mutate claim type or claim status;
- decide or imply coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure.

Existing intelligence/rule engines may consume domain classification only in a separately governed future tranche with explicit source lineage and regression coverage.

## Initial taxonomy
Incident domains:
- Machinery Failure
- Collision
- Grounding
- Fire
- Cargo Damage
- Pollution
- Salvage
- General Average

Machinery components:
- Main Engine
- Turbocharger
- Generator
- Propeller
- Steering Gear
- Boiler
- Pump

## Consequences
### Positive
- preserves the meaning of existing `ClaimType`;
- supplies a stable marine-domain context for later retrieval, similarity and intelligence work;
- avoids duplicating existing rules/evidence/intelligence architecture;
- gives classification changes auditable human provenance and tamper-evident lineage;
- permits future taxonomy expansion through explicit catalog versions.

### Trade-offs
- the catalog is intentionally narrow in Phase 16.1-A;
- classifications do not yet drive rule execution or intelligence generation;
- a future catalog change requires an explicit version bump and compatibility decision rather than silent mutation.

## Follow-up
Phase 16.1-B may add governed consumption of the classification lineage by downstream intelligence or evidence-requirement presentation, but it must preserve human authority and source/version provenance.
