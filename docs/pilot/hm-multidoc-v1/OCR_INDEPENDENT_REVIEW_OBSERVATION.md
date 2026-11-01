# R5 — independent OCR original-scan observation (no source clearance)

Related: [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850),
[#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810).

## Narrow claim-handler workflow

1. A handler records a source-matched, content-free OCR concern against
   a specific claim/document/source-text hash using the existing
   `POST .../source-discrepancies` endpoint.
2. A **different authenticated** human reviewer with the role **Claims
   Manager or Admin** independently examines the original scan and reports
   the observation via
   `POST .../source-discrepancies/{report_id}/independent-reviews`.
   The request binds the original file hash, OCR extraction hash,
   `review_method=visual_original_scan`, the asserted original-scan
   comparison checkbox, one of `discrepancy_observed`,
   `not_reproduced`, or `inconclusive`, and an opaque
   `review_workpaper_sha256`.
3. The resulting append-only Audit entry records the independent reviewer's
   database identity, original report ID, exact current source bindings,
   review outcome and workpaper digest. `GET` at the same path lists
   authenticated, tenant-scoped review receipts for that original report.
4. Exact same reviewer/source/report/outcome/workpaper retries return the
   *same receipt* with HTTP 200; a new observation returns HTTP 201.
   Production PostgreSQL locks the claim row for source revalidation and
   retry lookup.

## Hard safety boundaries

- The reviewer-provided workpaper digest is a **claim of association**,
  not evidence that the review workpaper has been ingested, signed,
  independently authenticated, or retained in a managed evidence store.
  An asserted original-source comparison is not machine-verified.
- **No outcome clears the original report**, including `not_reproduced`.
  Existing ClaimFacts, assessment source fingerprints, Claim Packs,
  reserves, coverage conclusions and approval authority remain unchanged.
- Original report remains `reported_unverified` and continues to trigger
  current-source revalidation/read-side warnings. Independent review is
  documented separately with `review_state=independent_observation_no_clearance`.
- Missing or mismatched report/source/version/hash, a reviewer who filed
  the report, unauthorized role, tenant mismatch or unauthenticated
  original source access fail closed.
- The read endpoint covers **currently valid source versions** only.
  Historical superseded report/review entries remain in the immutable
  Audit ledger; adding a controlled historical audit retrieval flow is a
  separate concern.
- No raw OCR transcript, personal claim narrative, correction content or
  workpaper bytes are written to this review receipt.

## Still required for #850 closure

A distinct and authorized adjudication/resolution workflow is needed to
verify workpaper custody, assign accountable decision authority, reconcile
multiple reviewer findings, authorize any source-dispute clearance or
source replacement, and persist read-side clearance semantics under the
claim lock. Never treat this observation as permission to promote critical
Persian machine extraction or start a real-data pilot.

**Pilot v1 for customer claims remains NO-GO.**
