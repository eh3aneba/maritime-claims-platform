# ADR-092: Canonical human-approved claim-fact provenance

- Status: Accepted
- Date: 2026-09-04
- Phase: 13.1B
- Parent: #155
- Implementation issue: #157

## Context

The existing `claim_facts` table is the current-value store for structured facts that have crossed a human-review boundary. It was introduced through the AI review workflow and therefore required every fact to reference a `DocumentExtraction` row.

Phase 13.1A makes H&M claim intake a durable, human-controlled workflow. On approval it already creates the real source `Document`, `DocumentTextExtraction`, and `DocumentTextSegment` rows. Requiring an intake-approved fact to manufacture an AI `DocumentExtraction` solely to satisfy the old foreign key would falsify provenance and blur the authority boundary.

A second fact table or a second `/facts` API would instead fragment the canonical claim state and make downstream reasoning depend on which intake path produced the value.

## Decision

`claim_facts` remains the single current-value store and `GET /claims/{claim_id}/facts` remains the single current-approved-facts API.

Each fact records exactly one human-review provenance path:

1. `ai_review`
   - `source_extraction_id` references the reviewed `DocumentExtraction`.
   - `source_text_extraction_id` is null.
2. `intake_review`
   - `source_extraction_id` is null.
   - `source_text_extraction_id` references the real `DocumentTextExtraction` created from the approved intake source.

A database check constraint requires exactly the lineage appropriate to the selected provenance kind. Existing rows are backfilled by the migration as `ai_review`.

The source `Document` remains mandatory for both paths. `source_segment_id` remains optional.

## Intake promotion rules

Only the persisted claim values produced by the explicit human approval action are promoted. Raw deterministic candidates never write to `claim_facts`.

Intake field paths use the `claim.*` namespace. Optional null values are not promoted.

A source segment is attached only when all of the following are true:

- the approved final value equals the extracted candidate for that field;
- field evidence contains a non-empty source quote; and
- that quote is actually present in the referenced text segment.

Human-edited values, defaults, relationship identifiers such as `vessel_id`, and other values without direct quoted support retain document/text-extraction provenance but receive no fabricated segment citation.

The approval transaction creates the claim, source document/text extraction/segments, canonical facts, intake review record, and audit entries before one commit. The already-approved-draft short circuit and promotion-level semantic no-op guard prevent duplicate facts or version drift on repeated approval calls.

## AI compatibility

The existing AI human-review path remains valid. New AI-reviewed facts receive the model/server default `ai_review` provenance and their existing `source_extraction_id`; their API field remains present, but is nullable because intake facts deliberately do not invent an AI extraction.

If a future workflow intentionally replaces a canonical `claim.*` intake fact from another reviewed source, it must explicitly replace the provenance fields together so the database constraint continues to describe the true source.

## Security and tenancy

Fact listing continues to reuse the tenant-scoped claim access check. Cross-tenant or deleted claims remain hidden. Provenance UUIDs never relax document or claim access controls.

## Consequences

- one canonical fact store and one facts API are preserved;
- intake evidence becomes traceable without fake AI records;
- downstream consumers can distinguish provenance while remaining compatible with existing AI facts;
- direct segment citations are conservative rather than inferred;
- downgrade from 0065 removes `intake_review` facts before restoring the old non-null AI-extraction schema because the older schema cannot truthfully represent them.

## Non-goals

This ADR does not authorize autonomous fact approval, coverage/liability decisions, reserve or settlement decisions, a new claim domain, or a parallel intake/AI authority path.
