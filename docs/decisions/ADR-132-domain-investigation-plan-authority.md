# ADR-132 — Governed domain investigation plan authority

- Status: Accepted for Phase 16.2-C
- Date: 2026-09-07
- Scope: Claim Intelligence / domain-aware investigation support

## Context

Phase 16.1 introduced a human-confirmed, append-only claim-domain classification. Phase 16.2-A/B then introduced a deterministic read-only domain investigation playbook registry and handler-facing preview.

The existing deterministic Rule Engine is not a read-only surface. Executing it synchronizes `ClaimDocumentRequirement` and `ClaimIssue` records and may participate in downstream task/document-request workflow. Therefore wiring a domain classification or playbook preview directly into Rule Engine execution would cross the authority boundary established for the playbook preview.

Handlers still need a controlled way to turn useful preview prompts into an explicit case investigation scope without granting those prompts rule, task or claim-decision authority.

## Decision

Phase 16.2-C introduces an append-only `ClaimInvestigationPlan` lineage as a separate human-authority boundary between a read-only playbook and any future executable workflow.

### Preview authority

The domain playbook preview remains live, read-only and derived from the current human classification. It may change immediately after reclassification or application registry change. It has no mutation authority.

### Plan authority

A handler may explicitly adopt a bounded subset of the exact current playbook's:

- investigation tracks;
- evidence prompts;
- review topics.

Adoption freezes:

- exact classification id, catalog version, sequence and SHA-256 hash;
- exact playbook registry version and SHA-256 hash;
- incident/component/failure-mode context;
- canonical selected items in registry order;
- contextual Marine Registry IDs as references only;
- human adopter and adoption note;
- append-only plan sequence and previous/current integrity hashes.

The client cannot supply or override contextual rule references.

### Stale-source behavior

Reclassification or registry change never rewrites an adopted plan. The prior plan remains immutable and is surfaced as stale-by-source. A new explicit adoption is required to establish a current plan version.

### Idempotency

Exact replay of the same claim, classification source, registry source and canonical selected items returns the already-adopted plan rather than creating duplicate plan lineage. A changed human note alone does not create a new plan for an otherwise identical adoption selection.

## Explicitly not authorized

Investigation-plan adoption creates zero automatic:

- `RuleEvaluationRun` records;
- `ClaimDocumentRequirement` records;
- `ClaimIssue` records;
- Claim Facts;
- claim tasks or document-request batches;
- Claims Intelligence snapshots;
- correspondence or evidence mutations;
- coverage, causation, fault, liability, fraud, recoverability, governing-law, legal time-bar effect, reserve, settlement, payment or closure decisions.

Contextual Marine Registry IDs remain references only. Plan adoption does not evaluate or trigger those rules.

## API contract

The claim-scoped API exposes:

- current Investigation Plan;
- append-only plan history;
- explicit plan adoption.

Adoption fails closed unless the supplied classification and registry hashes still match the live server-side preview. Selected items must be exact members of the live canonical playbook and at least one item must be selected.

## UI contract

Claims Intelligence may display the live preview beside the current adopted plan and its history. The plan workspace may select canonical items, require a human note and explicit confirmation, and show current/stale source lineage.

It must not offer `Apply Rules`, automatic document request, automatic task creation or equivalent workflow-execution controls in Phase 16.2-C.

## Consequences

This creates a useful handler-owned investigation scope while preserving a clean authority ladder:

1. human claim-domain classification;
2. live read-only playbook preview;
3. explicit immutable human Investigation Plan;
4. any future transition into executable requirements/tasks/rules must be separately designed, reviewed and authorized.

The extra boundary intentionally avoids treating a taxonomy/playbook as an automatic claims-control engine.
