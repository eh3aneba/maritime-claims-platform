# ADR-015: Keep core claims rules deterministic and independent from LLMs

## Status
Accepted

## Context
Marine claims workflows require explainability, repeatability, auditability and safe human oversight. Missing-document rules, stage gates and simple technical comparisons should not vary with an LLM response.

## Decision
Core claims workflow rules are implemented as versioned deterministic backend logic. They consume authoritative claim fields, active documents and human-approved `claim_facts`. LLM outputs cannot directly trigger a technical rule until reviewed and promoted by a human.

Each persisted requirement or issue stores the generating Rule ID and Rule Version, and each evaluation creates an auditable `rule_evaluation_runs` checkpoint.

## Consequences

- The same reviewed inputs produce the same rule outcome.
- Rule explainability can show trigger data directly.
- LLM provider/model changes do not silently change workflow controls.
- Tenant-specific configuration can later be layered over a stable rule interface.
- Rules remain intentionally narrower than expert human judgment and must not be mistaken for coverage or causation decisions.
