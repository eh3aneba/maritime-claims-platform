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
