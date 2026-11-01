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

The warning is an API signal, not a watermark in an older already-downloaded
file, and cannot retract external copies or force an offline recipient to
notice later discrepancies. Operators must separately notify downstream
recipients when required by case-handling policy.

## Retry-safe, append-only source reports

An identical retry from the **same authenticated reporter** for the same
organization, claim, original document/version/file hash, extracted text hash,
source segment and discrepancy kind now returns its original receipt with
HTTP 200 instead of inserting a second audit entry. A fresh report still
returns HTTP 201. Another genuinely distinct issue, source segment, source
version, or reporter can create its own independent report. This is audit
deduplication **within the exact identity scope**, not a substantive source
resolution, a deletion of evidence or a claim decision.

## What remains unfinished

Independent verification and explicit source-discrepancy resolution, including
traceable operator authority and original-scan review, are still required
under #850. OCR omission validation under #810 remains open. No automatic
clearance on OCR reprocessing or retrospective reapproval is allowed.

**Real-customer-data Pilot v1 remains NO-GO.**
