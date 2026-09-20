# Phase 17.5-AF — changed/missing observation review handoff

Issue: #502

Base: `main@bb1f9df9035dd59ad179fb8265530bffb78a86a5`

## Goal

Bridge scheduled metadata observations to a human-review queue without turning metadata change detection into automatic content ingestion.

## Rules

- changed → one pending handoff;
- missing → one pending handoff;
- unchanged → no handoff;
- projection is DB-only;
- historical observation snapshot is immutable;
- no application User is synthesized;
- no provider/content/storage/Document/Evidence/processing/AI authority is added.

## Worker

`external_evidence_review_projector_worker` projects at most one eligible unprojected observation per iteration. Polling is bounded by configuration.

## Next

17.5-AG will define the explicit human review/authorization decision for a pending handoff before any remote-content refresh workflow.
