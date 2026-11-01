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

### Read-only browser history

In the claim's Evidence panel, open **Inspect machine OCR text**. Each current,
source-matched discrepancy report offers **Independent review history**. This
loads at most the most recent 25 recorded observations on demand. A history
access failure is not an empty history; stale source reports do not request
current-source review history. Mismatched hashes, duplicate/malformed rows or
any response claiming approval/clearance reject the entire page.

For an observation, **Managed workpaper record** reads its existing audit link
and displays the document ID, version and exact hash only when the response
matches that report/review/workpaper digest. This is historical metadata linkage,
not a download, a current byte-integrity check or verification of workpaper
content. An inaccessible or absent link is reported as unverifiable, not as
proof no workpaper exists. No write/approval controls are supplied by this view;
`not_reproduced` still cannot clear a hold. English/Persian labels share these
limits. Existing reviewer recording/authorization endpoints remain unchanged.

Validation commands:

```bash
cd apps/web
node tests/ocr-review-readback.test.cjs
npm run typecheck
npm run build
```

With a loopback frontend running and the locked browser dependencies installed:
`MCRI_WEB_URL=http://127.0.0.1:3000 python tests/browser/ocr_independent_review_readback_e2e.py`.
The browser regression intercepts all API responses with synthetic fixtures and
asserts zero API writes; it does not establish actual human review or OCR quality.
Both contract and browser regressions run inside the existing CI jobs.

### Unchanged authority and source limits

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
