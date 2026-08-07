# ADR-013 — Build chronology only from human-reviewed evidence

## Status
Accepted — Sprint 3 Phase E

## Decision
Chronology events and evidence conflicts are generated only from AI extractions whose human review status is `approved` or `edited`.

## Rationale
A timeline is an investigation artifact with higher authority than an AI suggestion queue. Allowing pending AI output directly into chronology would blur the product's Human-in-the-Loop boundary and could make unverified timestamps appear official.

## Consequences
- Pending and rejected AI candidates never enter active chronology.
- Repeatable Engine Log evidence remains outside scalar `claim_facts` but can become chronology evidence after review.
- Conflict detection is deterministic and auditable.
- Human conflict resolution does not modify or overwrite the source evidence.
