# Engine Log Intelligence — Sprint 3 Phase D

## Purpose
Engine logs are repetitive operational evidence, not scalar claim metadata. Phase D extracts source-linked machinery rows/events while preserving the distinction between AI candidates, human review, and future chronology events.

Pipeline:

`engine log -> text/sheet segments -> ai_extract_engine_log job -> strict engine_log_v1 schema -> row-granular document_extractions -> human review -> chronology input (Phase E)`

## Schema v1
Each source-order event can contain:
- date / time / explicit timezone
- event type label
- engine RPM / load
- turbocharger speed
- exhaust temperature
- lube-oil pressure
- alarm
- shutdown / restart
- action
- remarks

Measurements preserve raw source wording and also receive a non-destructive numeric normalization when possible. Missing values remain null; the AI is forbidden to interpolate or invent log values.

## Evidence semantics
- Direct log entries and measurements are `fact` candidates.
- `event_type` is an `inference` label used only to organize the evidence; it is not a causation finding.
- Every non-null value must reference a source segment and exact quote.
- Source quotes are verified against the extracted page/sheet text.

## Repeatable-event boundary
Engine-log rows are intentionally **not promoted to scalar `claim_facts`**. A claim can contain hundreds of timestamps/RPM/alarm values, so treating these as one current scalar fact would overwrite valid historical evidence.

Human review still applies to every extraction. Phase E will group reviewed engine-log extraction paths into chronology events while retaining their document/source identity.

## Event candidate API
`GET /api/v1/claims/{claim_id}/documents/{document_id}/intelligence/engine-log/events`

groups the latest engine-log AI run into source-order event candidates and exposes:
- normalized values
- per-field human review states
- source verification
- source locators/quotes
- timestamp candidate
- whether review is complete for the candidate

This endpoint does not create official chronology records in Phase D.

## Background job
The durable queue now supports `ai_extract_engine_log`. The same text-extraction, retry, confidentiality and tenant controls used by CE Report Intelligence apply.

## Confidentiality
External AI remains opt-in. Restricted evidence is blocked from an external OpenAI adapter unless `ALLOW_EXTERNAL_AI_RESTRICTED=true` is separately enabled.

## Phase E boundary
Phase E will create the Chronology Engine and Evidence Conflict layer. It will combine human-reviewed CE Report evidence, reviewed Engine Log events and later document sources without treating AI-generated event labels as ground truth.
