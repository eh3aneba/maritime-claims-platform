# ADR-133 — Explicit human Investigation Plan work activation

- Status: Accepted for Phase 16.2-D
- Date: 2026-09-07
- Scope: Claim Intelligence / investigation workflow authority

## Context

ADR-132 established a deliberate authority ladder:

1. human claim-domain classification;
2. live read-only domain playbook preview;
3. explicit immutable human Investigation Plan;
4. any transition from the plan into executable workflow must be separately designed and authorized.

The existing deterministic Rule Engine is not a suitable implementation for step 4. `evaluate_claim_rules()` synchronizes `ClaimDocumentRequirement` and `ClaimIssue` records and then synchronizes requirement-linked tasks. Directly invoking that engine from an Investigation Plan would make the plan an indirect claims-control authority and would collapse the boundary created in Phase 16.2-C.

Handlers nevertheless need a controlled way to turn selected plan items into owned follow-up work.

## Decision

Phase 16.2-D adds a separate explicit human activation action. The action may create human-owned `ClaimTask` rows from exact items in the current immutable Investigation Plan, but it does not run rules or create external/document workflow authority.

### Activation prerequisites

Activation fails closed unless:

- the claim has a current Investigation Plan;
- the submitted plan id and SHA-256 match the current immutable plan;
- the plan still matches the live human classification/playbook source;
- the operator explicitly confirms activation;
- the human note contains at least 20 non-whitespace characters;
- at least one selected item belongs exactly to the immutable plan;
- every selected item key is server-derived from the plan and cannot be supplied as custom work text.

### Canonical plan-item identity

Plan items receive deterministic server-side keys based on their frozen plan order:

- `track:N` for investigation tracks;
- `evidence:N` for evidence prompts;
- `review:N` for review topics.

The server stores the key, item kind and exact frozen text inside the append-only activation record. The client cannot create custom activation text through this endpoint.

### Human task mapping

Selected items create only human-owned claim tasks:

- investigation track -> `FOLLOW_UP`;
- evidence prompt -> `FOLLOW_UP`;
- review topic -> `REVIEW`.

An evidence prompt is **not** a `ClaimDocumentRequirement` and does not create a `DocumentRequestBatch` or Correspondence draft. A later external request remains a separate explicit claims-control action.

Task provenance records the exact Investigation Plan, activation and item key. The existing `TaskSource.HUMAN` value is preserved because the authority is the human activation, not the playbook or Rule Engine.

### Activation lineage and idempotency

`ClaimInvestigationPlanActivation` is append-only and freezes:

- claim and plan identity;
- plan sequence and SHA-256;
- canonical selected items;
- human activator and note;
- assignee and optional due date;
- activation sequence;
- prior/current activation hashes;
- deterministic activation-key hash.

Exact replay of the same plan + canonical item selection returns the existing activation. A plan item already activated from that plan cannot be activated again through a partially overlapping new activation; the request fails closed instead of creating duplicate tasks.

### Stale-source behavior

Reclassification or a newly adopted Investigation Plan never mutates a prior activation or its tasks. Existing work remains auditable and is surfaced as stale-by-plan-source. Activating work from a new plan requires another explicit human activation.

## Explicitly not authorized

Investigation Plan activation creates zero automatic:

- `RuleEvaluationRun` records;
- `ClaimDocumentRequirement` records;
- `ClaimIssue` records;
- `DocumentRequestBatch` records;
- Correspondence records;
- Claim Facts;
- Claims Intelligence snapshots;
- Evidence/Documents;
- provider/email actions;
- coverage, causation, fault, liability, fraud, recoverability, governing-law or legal time-bar effect;
- reserve, settlement, payment or claim closure decisions.

The action creates only its append-only activation record, audit metadata and the explicitly selected human tasks.

## API and UI contract

The claim-scoped API exposes:

- latest activation;
- activation history;
- explicit activation POST.

The Claims Intelligence UI may show current/stale activation lineage, select exact plan items, capture an optional due date, require a human note/confirmation and show resulting task status.

It must not expose `Apply Rules`, automatic document-request, automatic external correspondence or automatic Claims Intelligence build controls as part of this activation.

## Consequences

The authority ladder becomes:

1. human domain classification;
2. read-only playbook;
3. immutable human Investigation Plan;
4. explicit human activation into traceable internal tasks;
5. any later conversion into rule evaluation, evidence requirements, external document requests or correspondence remains a separate authority boundary.

This gives handlers useful operational follow-up while keeping taxonomy/playbook logic non-authoritative and preserving human ownership of claims-control actions.
