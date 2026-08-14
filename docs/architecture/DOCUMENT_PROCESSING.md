# Document Processing Architecture — Sprint 8 Phase A

## Goal
Move slow document work off the request path while preserving tenant isolation, evidence provenance, and provider neutrality.

## Pipeline

`Upload -> DB-backed job -> Worker -> Text extractor -> Source segments -> Processing summary`

Phase A created the processing foundation. Sprint 3 Phase B now enables explicit Chief Engineer Report AI classification/extraction on top of these source segments; see `AI_INTELLIGENCE.md`.

## Queue choice
The MVP uses PostgreSQL as a durable job queue. Workers claim pending jobs with `FOR UPDATE SKIP LOCKED` on PostgreSQL. This avoids introducing Redis/Celery before throughput requires it. The worker boundary is replaceable later.

## Text source model
Text is persisted as source-addressable segments rather than one opaque blob:
- PDF: one segment per page.
- DOCX: document body/table text as a document segment.
- XLSX: one segment per worksheet.
- JPG/PNG: local Tesseract OCR when enabled; otherwise marked `requires_ocr=true`.
- Scanned/near-empty PDF: rendered with `pdftoppm` and passed through bounded local OCR when enabled.

This preserves a path to page/sheet source attribution in later AI extraction phases.

## AI gateway
`app.ai.gateway` defines a provider-neutral contract. `AI_PROVIDER=disabled` is the default. No external AI provider is called in Phase A and AI has no direct database write authority.

## Worker
Run continuously:

```bash
python -m app.workers.document_worker
```

Process at most one job:

```bash
python -m app.workers.document_worker --once
```

Docker Compose includes a separate `worker` service sharing the same database and evidence volume as the API.

## Human-approved claim intake

The intake pipeline is deliberately separate from ordinary claim evidence:

`quarantine -> ClamAV clean verdict -> intake draft -> worker extraction/OCR -> editable candidates -> human approval -> Claim + source Document`

- Accepted sources are PDF, JPG, PNG and DOCX.
- The API does not create a Claim at upload or extraction time.
- Classification and field extraction are deterministic proposals with source quotes/confidence metadata.
- A reviewer must select an existing tenant vessel, check/edit every required field and record a review note.
- Approval promotes the clean source into active claim evidence and is idempotent.
- No candidate is promoted into `claim_facts`; later evidence review remains authoritative.

## OCR controls

- `OCR_ENABLED` gates OCR in the worker only.
- `OCR_LANGUAGES=eng+fas` provides English and Persian recognition.
- `OCR_MAX_PAGES` is capped in code at 100 and defaults to 20.
- `OCR_TIMEOUT_SECONDS` bounds each conversion/OCR process.
- Security rescan jobs retain worker priority over intake and ordinary processing.
