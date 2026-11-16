# R5: Bind an independent OCR review to a managed workpaper record

Issue: [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850).

## Operator sequence

1. Handler reports an unverified OCR source discrepancy on the current original
   document, retaining its file SHA-256, version, OCR text hash and source locator.
2. A **different** Claims Manager/Admin records an independent original-scan
   observation, attaching their asserted workpaper SHA-256. This action does not
   certify source text or clear the dispute.
3. The same independent reviewer uploads the review workpaper through the
   **existing governed claim-document intake** (not a new file upload bypass),
   selecting `document_type=ocr_review_workpaper`. A successful upload is
   malware-scanned by existing deployment policy, stored and hashed.
4. Only the reviewer who signed the independent observation can call:
   `POST /api/v1/claims/{claim_id}/documents/{document_id}/processing/source-discrepancies/{report_id}/independent-reviews/{review_id}/workpaper-binding`
   with `workpaper_document_id` and `workpaper_file_hash`.
5. The API requires that the workpaper be an existing, same-tenant/same-claim,
   current, nondeleted **CLEAN** document with scan timestamp, positive
   byte length, correct review-workpaper type, and uploader identity equal to
   the independent reviewer. Its stored SHA-256 must match both the request and
   the workpaper digest *already claimed in the review's immutable audit entry*.
   Current source/report/review hashes are revalidated under the PostgreSQL
   claim lock.
6. The append-only Audit linkage records source/report/review and the
   workpaper document id/version/file hash. Repeating an identical binding
   returns the original immutable receipt with HTTP 200. Conflicting rebinding
   is rejected. GET on the same path reads the existing receipt.

## Evidence scope, not automatic approval

The receipt state is `managed_clean_document_record_linked`: repository intake
metadata has been matched against a previously asserted digest. This does
**not** independently rehash bytes on every read, verify what the uploaded
workpaper *says*, prove the reviewer's skill or independence beyond account
identity, establish an original-page semantic match, or decide the claim.

A reviewer may assert `not_reproduced` while the original source remains
`reported_unverified`. The workpaper link **never** clears that source hold,
modifies an approved ClaimFact or assessment, changes coverage/causation/reserve,
authorizes settlement, or enables real-customer AI processing.

The earlier standalone digest-only independent-review receipts remain
historically readable as claimed metadata and do not gain workpaper custody
retroactively. **GET-only** readback of an existing managed-workpaper binding
remains available after the original document is superseded or its OCR text
hash is replaced by a subsequent processing run. This reads an immutable
historical statement, using the **original report/review extraction hash**,
unchanged document version/source-file hash, authenticated tenant/claim scope,
and the linked workpaper identity/digest from the original audit receipt.
Source evidence must remain clean, processed and processing-authorized;
changing the original file hash is not acceptable. A later-superseded
workpaper does not erase its historical binding. The readback does **not**
reverify current workpaper custody or cryptographic signer provenance.

The authenticated Evidence UI may also **show historical independent-review
observations and their managed workpaper linkage on demand** when the document
is still accessible but has since been processed into a different OCR text
hash. The UI compares each review to its **original report** source/hash and
displays an explicit historical/non-clearance warning rather than pretending
that its observations certify the currently extracted text. There are **no
browser mutations or approvals** in this readback; the source must still be
available through the controlled Evidence preview. Superseded originals
without an available preview are not silently brought back into the current
work queue, even though historical API receipts may remain readable.

**POST still requires the active original document, current original OCR
text hash, independent reviewer identity, and active managed workpaper.**
Reprocessing, supersession or changed source bytes never authorizes
a new old-source binding, hold clearance, claim-fact approval or re-review
of the original allegation.

## Open prerequisites

Issue #850 still needs authoritative human technical adjudication, rigorous
source-and-workpaper review (including checking actual referenced page and
negation scope), any explicitly approved source-resolution state transition,
and a human-held customer-pilot release decision. Persian critical OCR defect
#810 and production rehearsal #653 remain separate P0/P1 constraints.

**Real-customer-data Pilot remains NO-GO.**
