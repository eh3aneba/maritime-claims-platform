# Document Processing Architecture — Sprint 3 Phase A

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
- JPG/PNG: marked `requires_ocr=true`; OCR is not enabled yet.
- Scanned/near-empty PDF: marked `requires_ocr=true`.

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
