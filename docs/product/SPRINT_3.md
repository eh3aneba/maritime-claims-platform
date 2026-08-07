# Sprint 3 — AI Document Intelligence

## Phase A — Document Processing Architecture ✅

Delivered:
- PostgreSQL-backed durable document processing jobs
- Separate document worker process
- Automatic text-extraction job after evidence upload
- PDF page extraction with OCR-needed detection
- DOCX body/table extraction
- XLSX worksheet extraction
- Image OCR-needed detection without guessing content
- Source-addressable document text segments
- Processing summary and retry API
- Provider-neutral AI gateway with AI disabled by default
- Docker worker service
- Migration `0003_document_processing_foundation`

## Phase B — Next

Chief Engineer Report Intelligence:
- AI document classification
- CE Report structured extraction schema
- fact / opinion separation
- source segment attribution
- confidence values
- raw AI run persistence
- human review queue
- approve / edit / reject workflow

No AI-derived fact becomes approved claim data automatically.


## Phase B — Chief Engineer Report Intelligence

Completed:
- CE Report strict extraction schema v1
- document classification candidate + confidence
- facts vs source opinions
- source segment + exact quote attribution
- source quote verification
- `ai_runs` persistence with provider/model/prompt/schema versions
- `document_extractions` candidates with `pending` human status
- OpenAI Responses API adapter behind provider-neutral gateway
- PostgreSQL background job type `ai_extract_ce_report`
- external-AI confidentiality gate for Restricted evidence

No candidate is promoted into official claim facts in Phase B.

## Phase C — Human AI Review ✅

Completed:
- tenant-scoped global/claim-filtered AI review queue
- source-segment preview
- Approve / Edit / Reject
- append-only `ai_feedback` correction history
- human reviewer + timestamp audit trail
- authoritative `claim_facts` layer
- fact-only safe promotion rules
- non-promotion of opinions/inferences and sensitive decision paths
- stricter bulk approval for low-risk, high-confidence, source-verified metadata
- manual-verification reason required for unverified citations
- claim page display of approved structured facts

## Phase D — Engine Log Intelligence ✅

Completed:
- strict `engine_log_v1` structured schema
- source-order row/event preservation
- date/time and machinery operational fields
- non-destructive measurement normalization
- source quote verification per event field
- inference-only event labels
- durable `ai_extract_engine_log` background job
- grouped event-candidate API for Phase E
- human review compatibility without scalar claim-fact overwrite
- tenant and Restricted-document external-AI controls
- Claim Documents UI actions for CE Report and Engine Log intelligence

### Next — Phase E
Chronology Engine: combine reviewed CE Report evidence and reviewed Engine Log events, cluster matching events, and detect material timestamp/evidence conflicts.
