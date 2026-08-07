# Rules Engine & Missing Document Detection

## Purpose

The Rules Engine is a deterministic decision-support layer between human-approved claim knowledge and claims workflow actions. It is intentionally independent from LLM inference.

Current ruleset: `hm_machinery_rules` version `1.0`.

## Inputs

Rules use only:

- authoritative claim fields such as claim status and incident date;
- active claim documents and their human-assigned document type;
- `claim_facts`, which are human-approved structured facts.

Raw/pending AI candidates do not trigger technical rules.

## Persisted outputs

- `claim_document_requirements`: current-stage evidence requirements with priority, reason, rule/version and matched document.
- `claim_issues`: explainable investigation flags. They are not coverage or causation decisions.
- `rule_evaluation_runs`: append-only evaluation checkpoints with ruleset/version, trigger and summary.

## Stage-aware requirements

A requirement appears only after its `required_from_status` is reached. Example:

- Chief Engineer Report, Engine Log and Policy activate at Triage.
- Workshop Report and turbocharger maintenance evidence activate at Investigation.
- Repair quotation activates at Financial Review.
- Final Repair Invoice activates at Settlement.

Conditional requirements include towage, Class attendance and temporary repair evidence.

## Turbocharger scope

The turbocharger rule context is selected from human-approved equipment facts where available. The incident description may be used only as a deterministic scope fallback; it does not create an authoritative technical fact.

## Readiness

Document requirements are weighted:

- Critical = 4
- Important = 2
- Supporting = 1

Mandatory claim-intake fields contribute 10 points and current-stage document completeness contributes up to 90 points.

Readiness state:

- `not_ready`: at least one Critical requirement is unsatisfied.
- `limited`: no Critical requirement is missing, but Important requirements remain.
- `ready`: all active Critical and Important requirements are satisfied.

`requested` does not satisfy a requirement. `received`, `under_review` and `accepted` do.

## Technical rules v1

- `TECH-001`: running hours since overhaul exceed reviewed recommended interval → Possible overdue maintenance issue.
- `TECH-002`: casualty within 90 days after reviewed overhaul date → recent-overhaul/workmanship review issue.
- `TECH-006`: reviewed temporary-repair fact → permanent-repair/Class follow-up issue and conditional document requirements.

These are investigation flags only. They never establish causation.

## Automatic triggers

Evaluation currently refreshes after:

- explicit `POST /claims/{claim_id}/rules/evaluate`;
- claim status change;
- document upload;
- document soft delete.

A manual refresh remains available in the UI.

## Auditability

Every evaluation creates a `rule_evaluation_runs` row and an `EVALUATE_CLAIM_RULES` audit event. Requirements and issues retain the rule ID and version that generated them.

## Current limitations

- Customer-specific rule editing is not yet exposed.
- Requirement request/accept/reject workflow controls will be added with task/document-request workflow.
- Policy-specific clause logic and financial quote/invoice rules are later Sprint 4 phases.
- Rules do not approve/reject claims, determine coverage, determine liability or settle claims.
