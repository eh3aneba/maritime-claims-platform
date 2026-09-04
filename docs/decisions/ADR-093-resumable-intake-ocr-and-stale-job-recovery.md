# ADR-093: Resumable intake OCR and stale-job recovery

## Status
Accepted for Phase 13.1C.

## Context

H&M claim intake already stores uploaded source documents and durable processing jobs, but three production-maturity gaps remained:

1. a worker that disappeared after claiming an intake job could leave the job in `RUNNING` indefinitely;
2. PDFs containing a mixture of useful native text and scanned/low-text pages needed selective local OCR without discarding the good native text;
3. the operator UI stopped automatic polling after a bounded period and could leave a valid durable draft difficult to resume after refresh.

These are maturity/recovery concerns for the existing intake workflow. They do not create a new claim domain, a new source of authority, or an autonomous approval path.

## Decision

### 1. Stale worker leases are recovered conservatively

The document worker calls stale-intake recovery before claiming new intake work.

A `RUNNING` intake job is eligible only when its `locked_at` lease is older than the configured stale threshold. Recovery reuses the existing attempt budget:

- when attempts remain, the job returns to `PENDING` and keeps its current `attempt_count`;
- when the final permitted attempt has already been consumed, the job becomes terminal `FAILED`;
- the related intake draft remains `PROCESSING` only for an actual queued retry and becomes `FAILED` when the attempt budget is exhausted;
- recovery writes an audit record identifying the expired worker/lease state.

Recovery does not silently reset attempts and does not grant an unlimited retry loop. An explicit authenticated human retry remains available after terminal failure.

### 2. Mixed PDFs use selective local OCR

Native PDF extraction remains the first pass. Pages with meaningful native text are preserved unchanged. Only pages below the low-text threshold are candidates for local OCR.

Selective OCR:

- uses the configured local Tesseract language set, currently supporting `eng+fas`;
- rasterizes only eligible low-text pages;
- preserves page locators and the deterministic segment ordering;
- replaces a low-text page segment only when OCR actually returns text;
- keeps useful native/previously recovered text if later OCR pages time out or fail;
- enforces a configured page ceiling and overall timeout;
- records explicit warnings for page caps, unavailable OCR tooling, timeout, failed pages, and unresolved low-text pages;
- leaves `requires_ocr=true` whenever low-text pages remain unresolved.

The final `text_hash` continues to be derived deterministically from the stored ordered text segments. OCR warnings are processing metadata, not claim facts.

### 3. Long-running intake stays resumable and observable

The browser may poll automatically for a bounded period, but reaching that client-side bound is not a processing failure.

For an active draft, the UI:

- keeps displaying the durable draft status and opaque draft UUID;
- offers an explicit **Check status** action while processing is still running;
- stores only the active draft UUID in `sessionStorage` so a refresh in the same browser session can re-fetch the tenant-scoped draft;
- never stores uploaded evidence text, extracted fields, document bytes, review notes, claim facts, or credentials in browser storage;
- clears the resumable pointer after approval, rejection, or another terminal state that no longer needs recovery;
- relies on the existing authenticated API and tenant filtering when restoring a draft; an inaccessible/stale pointer is cleared.

This session pointer is convenience state only. The authoritative draft/job state remains in the database.

## Consequences

- Worker crashes no longer strand eligible intake work indefinitely.
- Automatic recovery remains bounded by the pre-existing attempt budget and audit trail.
- Mixed scanned/native PDFs can improve text acquisition without sacrificing already-good evidence text.
- Partial OCR cannot masquerade as complete extraction because unresolved pages and warnings remain explicit.
- Operators can refresh or return to the intake page within the same browser session without uploading the source again.
- No new autonomous claim/fact approval, coverage decision, liability decision, reserve authority, settlement authority, or AI production authority is introduced.

## Verification

Phase 13.1C requires:

- backend tests for stale lease requeue and final-attempt terminal failure;
- backend tests for mixed native/OCR extraction, page caps, timeouts, partial preservation, stable locators and deterministic text hash;
- EN/FA OCR configuration coverage;
- browser E2E proving the active draft survives refresh, resumes through the tenant-scoped API, remains human-reviewed, and clears the browser pointer after successful approval;
- existing full CI, migration, browser and Supply Chain Security gates on the exact PR head before merge.

## Out of scope

- external/cloud OCR or external AI classification;
- automatic translation of source evidence;
- autonomous acceptance of extracted fields or document classifications;
- new claim domains;
- chronology, financial, recovery/time-bar or settlement redesign;
- any new legal, coverage, liability, reserve, payment or settlement authority.
