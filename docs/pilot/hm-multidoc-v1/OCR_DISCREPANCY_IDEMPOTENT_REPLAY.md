# R5 OCR source discrepancy — exact retry and audit integrity

Tracking: [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850).

An authenticated operator can report a source OCR concern using the existing
content-free POST `/source-discrepancies` route. The report is an **unverified
operator allegation**; it never certifies a corrected transcript or an
independently adjudicated H&M claim fact.

## Same-operator idempotent replay

If the same operator retries with the exact **organization, claim, document,
current document version, original file SHA-256, extracted text SHA-256,
source segment and source locator, and discrepancy issue kind**, the endpoint
returns the original immutable audit receipt with **HTTP 200**, not a second
audit entry. The first valid report returns **HTTP 201**. An operator may
report a separate issue kind or another source segment; another reporter can
submit an independent observation. No existing audit entry is deleted.

The prior receipt lookup occurs **inside the existing PostgreSQL claim-row
lock**, after revalidating the current source/extraction and segment. This
serializes simultaneous same-claim reporting and approval paths when the
production PostgreSQL database is used.

The existing live Claim Pack source advisory counts matching audit receipts.
This guard prevents a network retry from artificially inflating that count.
It does not imply all claims or source-derived facts were verified or reviewed.

## Remaining holds

An OCR reread, retry or duplicate-receipt return never clears an active
source concern. An independent, traceable original-scan adjudication path
is still required before clearing affected critical source flags.
Historical human approvals remain immutable. Persian negation/OCR semantic
quality and the real-customer Pilot release gate remain **unproven / NO-GO**.
