# R5 Persian H&M OCR — independent source-validation protocol (draft)

**Status: DESIGN ONLY / NO HUMAN REVIEW PERFORMED / PILOT NO-GO.**
Issue: [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810).
This is an acceptance-study specification, **not** a report of successful OCR,
human verification, security approval, or real customer permission.

## What the current synthetic regression proves

The public invented HM-05 image contains a machinery term and the clause
`علت قطعی خرابی هنوز معلوم نیست و بررسی سوابق ضروری است.`.
The real Tesseract + persisted lexical-search browser journey records:

- Retrieval of the standalone machinery term `توربوشارژر`;
- Retrieval of the standalone negation token `نیست`;
- **Separately**, retrieval of the *entire reference clause in one*
  page-located, matching-file-version-and-hash search snippet.

These three **observations** are distinct. A successful keyword query can
coexist with an absent full clause, and a complete literal clause is not proof
that the OCR preserves negation scope in other source sentences. A failed
retrieval query also cannot by itself distinguish OCR omission from search
indexing/snippet truncation. The existing `text_hash`, file hash, version,
page locator and extraction method must be retained for forensic diagnosis.
HM-05 is public regression engineering material, **not an unseen benchmark**.

CI passes only when the pipeline remains observable and never fabricates
critical-fact authorization. `full_transcription_verified`,
`negation_scope_verified`, `critical_fact_authorization_granted` and
`pilot_accepted` remain **false**, irrespective of lexical probe success.

## Current diagnostic: persisted extraction vs search

Authorized handlers can inspect a **bounded, read-only** machine text
preview from
`GET /api/v1/claims/{claim_id}/documents/{document_id}/processing/source-segments`.
The endpoint enforces tenant + claim + document scope, clean/processed Evidence
and existing external-Evidence processing-release authorization. It returns
source file hash, extraction hash, version, method, page locator, byte-agnostic
character count, and explicit `text_truncated` flags. Responses are
`Cache-Control: no-store`. This endpoint does **not** provide a reviewer
approval workflow, a source image rendering or a verified transcription.

For the **synthetic** HM-05 PNG only, the E2E test now compares the complete
(untruncated) one-page persisted OCR transcript with the fixed negative
clause and separately executes an exact-phrase lexical search. This
distinguishes a clause absent in stored OCR (extraction/persistence stage)
from a clause present in OCR but absent in search (index/query/snippet stage).
If the stored preview is truncated, the test fails rather than asserting
that unobserved text was absent. The test validates stored-transcript hash
and source/version/page binding, but does not log raw text or claim
OCR scope fidelity. Even when both checks pass, the independent blinded
human source study is still required.

## Human-handler review aid (no approval workflow)

The Evidence & Documents screen now provides an on-demand
**Inspect machine OCR text** control for a current, clean, processed,
locally authorized OCR source. It shows the bounded persisted text preview
with page/segment locator, an explicit truncation warning, and a separate
**Download original for comparison** action. The browser checks
document version, original file hash and extraction text hash against the
selected source before displaying a preview. Closing the panel clears the
transcript from its component state; the response is requested without
browser caching. No transcript or original is put in public CI logs.

This aid does **not** display or certify the original page inline. It
does not record which original sentences a reviewer checked, cannot fix a
missing negation, and has **no approve/accept** action. Human reviewers
must use the unchanged source file and the separate controlled protocol
below. A green UX test is not evidence that any reviewer has completed
this comparison. Issue #810 and pilot NO-GO remain unchanged.

## Required independent reference study (not yet carried out)

1. Assemble a *separate, previously unseen* permission-cleared cohort of
   Persian maritime machinery documents, stratified by native scans/photos,
   resolution, rotation, print/handwriting, mixed-script technical terms and
   negation/uncertainty/temporal/causal qualifiers. Set minimum sample size,
   inclusion criteria and acceptance thresholds **before** model comparison;
   these have not been approved. Do not reuse public HM-05 as the blind set.
2. Have two independent, qualified bilingual reviewers compare every source
   page against a verbatim reference transcription; a designated maritime
   specialist adjudicates discrepancies affecting machinery, timelines,
   coverage/causation or negation scope. Reviewer identities, dates,
   conflicts and documented decisions belong in a controlled audit store,
   **not** invented fields in synthetic CI JSON.
3. For each critical reference span record document/version/source hash,
   page (and bounding region where possible), span type, exact transcription,
   reviewer disagreement/adjudication, OCR text/version/hash, and whether the
   phrase exists in the **OCR text** and separately in the **search result**.
   Record substituted negations, dropped qualifiers, added words, wrong
   scope, page attribution drift and undecidable scans explicitly.
4. Report denominators and per-category missed-spans/false-insertions,
   precision and recall (with uncertainty intervals), full-phrase fidelity,
   page/hash provenance accuracy, reviewer disagreements and correction
   time. Do not collapse these into a single generic OCR-success number.
   Isolate OCR-vs-search failures before selecting preprocessing or a
   different engine; repeat on an **untouched** evaluation cohort.
5. Independent H&M/domain owner and security reviewers must sign off a
   predetermined decision rule, exception handling, deployment/data
   controls, and fallback manual handling. Any material unresolved
   negation/scope error blocks machine-derived causation or coverage
   assertions, even with a successful worker status.

## Boundary and privacy

Only deliberately fictional sources belong in repository fixtures or
public CI artifacts. No actual scanned documents, raw transcriptions,
customer identifiers or reviewer personal data should be committed.
Real-case evidence requires separate authorization, jurisdiction/contract
review and approved secure processing. No external AI endpoint is enabled
by this document. Manual source comparison does not delegate claim
approval. Pilot remains **NO-GO** until the independent evaluation and
other R0–R5 security, operations and model-quality gates pass.
