# ADR-131 — Handler-facing domain investigation playbook preview

- **Status:** Accepted
- **Date:** 2026-09-07
- **Decision owners:** Claims product / engineering
- **Related:** ADR-127, ADR-128, ADR-129, ADR-130, Phase 16.2-B / Issue #241

## Context

Phase 16.2-A added a versioned, deterministic, read-only domain investigation playbook registry and claim-scoped preview API. The backend deliberately has no apply/activate transition: a playbook preview can organize investigation thinking but cannot execute rules, activate evidence requirements, create tasks or make substantive claim decisions.

Handlers need to see that preview in the existing Claims Intelligence workspace. The UI must preserve two distinctions already established by Phase 16.1 and ADR-130:

1. human claim-domain classification is a controlled contextual record;
2. the live playbook preview is not an immutable Claims Intelligence snapshot and is not workflow authority.

## Decision

We will render a dedicated **Domain investigation playbook** panel directly below the human claim-domain classification workspace.

### Read-only API consumption

The panel consumes only:

`GET /claims/{claim_id}/intelligence/domain-playbook-preview`

It contains no POST/apply/activate request path and exposes no control that creates a task, requests a document, executes rules or builds Claims Intelligence.

### Unclassified state

When the preview API returns `classification_required=true`, the UI explains that a human claim-domain classification is required and renders no incident-specific playbook. It does not infer a default incident from the catalog or from claim text.

### Classified state

For a classified claim, the panel renders the canonical preview response only:

- incident title;
- optional component and failure mode;
- playbook objective;
- investigation tracks;
- evidence prompts;
- review topics;
- contextual Marine Registry rule IDs;
- classification sequence and integrity lineage; and
- playbook registry version/hash.

Contextual rule IDs are explicitly labeled as **references only**. Their presence does not mean a rule has been evaluated, triggered or adopted.

### Classification-note separation

The playbook endpoint does not return the human free-text classification note and the playbook panel must not obtain it from the adjacent classification UI. The note remains visible only in the controlled classification record/history.

### Immediate preview refresh after classification

After the existing classification POST succeeds, the classification component dispatches a claim-scoped browser event. The playbook component listens for that event and re-fetches only the read-only preview endpoint for the same claim.

This refresh signal:

- does not call the Claims Intelligence build endpoint;
- does not evaluate rules;
- does not mutate requirements/issues/tasks/facts;
- does not modify an existing immutable Intelligence snapshot.

This means a newly recorded reclassification can immediately switch the live playbook preview while the previous Claims Intelligence snapshot intentionally continues to show its prior source state until the handler separately chooses **Refresh Intelligence**.

### Authority boundary

The UI must not expose an Apply, Activate, Create task, Request document or equivalent mutation control in this tranche.

Viewing or refreshing the playbook must not create or imply a decision on:

- coverage;
- causation;
- fault or liability;
- recoverability;
- governing law;
- legal time bars;
- reserves;
- settlement;
- payment; or
- claim closure.

Any future transition from a preview prompt to an active rule, requirement or task requires a separately designed explicit human-authority workflow.

## Consequences

- Handlers receive useful domain-specific investigation structure immediately after classification.
- The UI makes the distinction between live contextual preview and immutable Intelligence snapshot visible rather than hiding it.
- No backend schema, migration or new mutation endpoint is required.
- The existing Phase 16.1 explicit Build/Refresh Intelligence contract remains unchanged.
- The human classification note remains bounded to its original controlled surface.

## Verification

The existing MT ORION claim-domain browser regression is expanded to prove:

1. an unclassified claim shows a classification-required playbook state and no fabricated playbook;
2. saving Machinery Failure immediately displays the machinery playbook while Claims Intelligence remains unbuilt;
3. machinery evidence prompts and contextual rule references are visible but labeled as non-evaluated references;
4. the classification note is absent from the playbook panel;
5. the playbook panel has no mutation button;
6. source lineage exposes the classification sequence/hash and registry identity;
7. reclassification to Collision immediately changes the live playbook while the already-built Intelligence snapshot remains Machinery Failure; and
8. only a separate explicit Refresh Intelligence updates that immutable snapshot to Collision.

The normal repository gates remain required before merge: backend full suite, PostgreSQL/Alembic preflight, frontend typecheck/build, Docker validation, MT ORION browser E2E, Operational Performance Smoke, Production Deployment Policy and Supply Chain Security.
