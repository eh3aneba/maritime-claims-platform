# ADR-012 — Keep repeatable operational evidence outside scalar claim facts

## Status
Accepted — Sprint 3 Phase D

## Context
`claim_facts` represents the current human-approved scalar knowledge of a claim. Engine logs produce repeated values such as timestamps, RPM, alarms and actions. Promoting each engine-log extraction into a unique scalar field would either overwrite earlier evidence or force document-specific field names into the canonical claim-fact layer.

## Decision
Engine-log event fields remain human-reviewable `document_extractions` and are explicitly non-promotable to scalar `claim_facts`. Canonical identity metadata such as vessel name or IMO may continue to use the scalar fact layer.

The Chronology Engine will consume reviewed repeatable evidence directly and create separate event records with many-to-many evidence links.

## Consequences
- Historical engine-log rows cannot overwrite one another.
- Review and audit history are preserved per extraction.
- Chronology remains an explicit derived domain layer rather than an accidental side effect of scalar facts.
- Future alarms, noon reports and other time-series evidence can reuse the same pattern.
