# R5 — live OCR source concern notice for immutable Claim Pack history

Tracking: [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850), [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810).

## Why

A Claim Pack generated and downloaded **before** an operator reported a later
negation/date/technical-term discrepancy remains an immutable historical
artifact. Editing the archived PDF/XLSX would falsify its export-era byte and
snapshot hashes. Conversely, presenting only its old "reviewed" snapshot
without telling the claim handler about a **currently reported** source concern
would be misleading.

## Read-time advisory

- `GET /api/v1/claims/{claim_id}/claim-pack-exports` now has a top-level
  `current_unverified_ocr_source_report_count`, distinct from the immutable
  `items` array and the export-era snapshot hashes.
- `GET /api/v1/claims/{claim_id}/claim-pack-exports/{export_id}/download`
  adds `X-Claim-Current-Unverified-OCR-Source-Report-Count` while preserving the
  stored original bytes, Content-Disposition and SHA-256 headers.
- This is a **claim-wide advisory** counting operator-report audit receipts that
  still match the tenant, claim, **current document version and original file
  hash**, not a per-export attribution or a verified source error.
- A value of **0 means no currently matching reports**, **not** "verified source."
  A value greater than 0 means **consult the original scan and independent
  reviewer before relying on source-derived critical conclusions**. No
  coverage, causation, reserve, payment or settlement decision is changed.
- Historical human approvals, ClaimFacts, assessment content, audit lineage and
  old PDF/XLSX bytes remain unmodified. A new Claim Pack generated *after* a
  matching report carries the existing source revalidation warnings in its
  own immutable snapshot.

The Claim Pack web page now displays this claim-wide current-source advisory
when the API count is positive. Before every download, the browser queries the
fresh count again: when the count is positive, it asks the operator to
explicitly acknowledge that the archived export may predate the report. If the
fresh read fails, the download is not initiated by the page. This is an
on-screen human-warning control, **not** a server-side source-certification
check, an assertion that the particular export is wrong, or a substitute for
independent original-image review. In particular, an earlier recipient who
already holds a file cannot be recalled or notified by the browser.

The warning is carried on the API response and in the current browser view,
not watermarked into an old PDF/XLSX. Operators must separately notify
downstream recipients when required by claim-handling policy.

## What remains unfinished

Independent verification and explicit source-discrepancy resolution, including
traceable operator authority and original-scan review, are still required
under #850. OCR omission validation under #810 remains open. No automatic
clearance on OCR reprocessing or retrospective reapproval is allowed.

**Real-customer-data Pilot v1 remains NO-GO.**
