# AI Document Intelligence — Sprint 3 Phase B

## Scope
Phase B enables the first controlled AI workflow for one document class: **Chief Engineer Report**. The secured original document and extracted source segments remain the evidentiary source of truth.

Pipeline:

`document -> text segments -> explicit AI job -> structured CE schema -> source validation -> raw AI run + extraction rows -> human review (Phase C)`

## Safety boundary
- AI never writes directly to approved Claim, Vessel, Incident, Equipment, Coverage, Reserve or Settlement data.
- AI output is stored as `pending` extraction candidates.
- Facts and source opinions are separate semantic types.
- Inferences have a database type but are not produced by the CE v1 extraction prompt.
- Every non-null extracted value must include a source segment and quote.
- Quotes are verified against the referenced extracted text. A mismatch is retained but flagged, never silently trusted.
- User-provided `documents.document_type` is not overwritten by AI classification.

## Tables
### `ai_runs`
Persists reproducibility/audit metadata:
- task/status
- provider/model
- prompt name/version
- schema name/version
- input hash and character count
- document classification candidate/confidence
- raw structured output
- provider response id and token usage
- warnings/errors

The full source input is not duplicated in `ai_runs`; source text already exists in tenant-scoped text segments.

### `document_extractions`
One row per candidate field/list item:
- canonical `field_path`
- semantic kind (`fact`, `opinion`, `inference`)
- raw and normalized value
- confidence
- source segment/locator/quote
- source verification result
- human review status and future approved value

## CE Report schema v1
The current schema covers:
- document classification
- vessel/report/author identification
- incident date/time/timezone/location/voyage/cargo status
- equipment identity
- first observation and symptoms
- immediate actions
- operational impact
- suspected-cause **opinions**
- recommendations

Unknown or unsupported values must be null/empty rather than inferred.

## Provider gateway
`app.ai.gateway` remains vendor-neutral. Phase B adds an OpenAI adapter using the Responses API with strict JSON Schema structured output. `AI_PROVIDER=disabled` remains the default.

OpenAI use requires explicit environment configuration:

```env
AI_PROVIDER=openai
AI_MODEL=<supported-structured-output-model>
OPENAI_API_KEY=<secret>
```

No model name is hard-coded as the deployment default. This avoids silently binding the platform to a model lifecycle.

## Confidentiality control
`RESTRICTED` documents cannot be sent through the OpenAI external-provider adapter by default. An operator must deliberately set:

```env
ALLOW_EXTERNAL_AI_RESTRICTED=true
```

This flag is intentionally separate from simply enabling an AI provider.

## Background jobs
CE intelligence uses the existing PostgreSQL-backed queue with job type `ai_extract_ce_report`. Text extraction must have completed first and OCR-required documents are blocked until OCR exists.

## Phase C boundary
Review fields already exist in the database, but Phase B provides no approve/edit/reject mutation endpoint. Phase C will add the human review workflow and UI. Until then, all extracted candidates remain `pending`.
