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

## Append-only handler discrepancy receipt (operator-reported, not expert-certified)

The `POST .../processing/source-discrepancies` endpoint records one
**operator-reported** OCR source discrepancy on the existing immutable
organization-scoped audit ledger. The operator must attest that they
compared the original source with the machine transcript; the service
cannot independently prove that comparison happened. It binds to the
**exact current document version, file SHA-256, extraction-text SHA-256
and stored segment/page locator**, and refuses stale versions, missing
segments, dirty/unfinished evidence, unapproved external processing and
non-OCR extraction methods.

Only controlled kind codes are accepted: `negation_missing`,
`negation_scope_changed`, `date_time_changed`,
`technical_term_changed`, and `other_transcription_discrepancy`.
**No text, corrected wording, free-text rationale, or original image**
is submitted/stored in this report. `GET .../processing/source-discrepancies`
provides a tenant-scoped, bounded readback of immutable receipts with
reporter identity, timestamp, source locator and hashes.
Duplicate submissions are *distinct reports*, not automatic corrections.
A report always has `review_state=reported_unverified` and
`claim_fact_approved=false`. This is a **defect observation workflow**,
not adjudication, a two-reviewer verification ledger, signed go-live
authorization, or an OCR improvement itself.

## Handler discrepancy reporting UI (unverified observations)

On the document's **machine OCR comparison** pane, the authenticated
operator can select a visible, untruncated source segment and a controlled
discrepancy category. The **Record unverified discrepancy** action is
disabled until the operator explicitly attests personally comparing that
segment with the unchanged source. A browser-only CI check intentionally
does **not** provide this attestation or create a fake reviewer report.
The backend validates a current exact file/extraction/version/segment again
at submission; stale reports are denied. A successful response shows its
immutable audit receipt ID; users may view a bounded history of previous
*reported, not verified* observations.

This tool does not accept replacement text or rewrite recognized OCR.
Attestation only records the operator's **assertion**, not evidence that
a specialist independently confirmed their comparison. Reports neither
approve a Claim Fact nor change any OCR quality/GO gate. The history
returns up to 25 receipts and is not an exhaustive audit export.

## Offline critical-span measurement instrument (descriptive only)

`python -m scripts.persian_ocr_local_validation_metrics --input /secure/local/study.json`
runs entirely on the operator's machine. Keep private permission-cleared study
JSON **outside the repository**, public CI, terminal histories and connected
cloud folders. Never commit real reference scans or extracted text.
The instrument reads reference/recognized full-page strings in process memory
but emits **only aggregate JSON counts**, with no original text, identifiers,
raw spans or paths in stdout/stderr. It does not contact any external AI,
network endpoint, claims database or web service.

Input `schema_version: 1`, `records: [...]` contains one page per record:

- `case_ref`, `page_locator`, `document_version`,
  `source_file_sha256`, `extraction_sha256`,
  `reference_page_text`, `ocr_page_text`,
  `ocr_page_complete` (a real full-page, untruncated observation), and
  `critical_spans`.
- Each critical span contains a unique `span_ref`, `kind` (negation,
  uncertainty, time, causation, technical_term or other_critical_phrase),
  `literal`, `expected_present` and nullable `search_exact_hit`.
  The search flag must come from an **actual exact-phrase, same-source/page/
  version/hash retrieval attempt**; null means not tested. Unknown is NOT
  false. Negative-control literals must be absent from the reference and
  have a null search flag.
- All text is **literal**, intentionally not automatically normalized,
  repaired, paraphrased or matched by AI. A reference-positive phrase found
  in complete OCR counts as exact-literal present; absent counts as an
  extraction-stage miss. When OCR contains the phrase and exact search
  returns false, it counts as a conditional retrieval-stage miss. A
  reference-absent negative-control literal present in OCR counts as a
  possible false insertion. An incomplete OCR page contributes only
  **unknown**, never an inferred missing phrase.
- Output reports denominators and per-kind/total counts, descriptive
  Wilson 95% intervals for *measured* literal recall, and separate
  false-insertion/retrieval counts. The tool rejects contradictory reports,
  out-of-scope fields and inconsistent literal labels. These intervals do
  not correct biased/non-random sampling.

**This instrument checks the syntactic shape of hash metadata, not the
image bytes, reviewer qualifications, independent source/adjudication,
negation scope semantics, authorization or true holdout status.** Even if
all literal matches are observed, it always reports
`reference_transcript_independently_adjudicated=false`,
`negation_scope_semantics_verified=false`,
`human_bilingual_review_completed=false` and `pilot_accepted=false`.
The only checked-in examples are deliberately fictional. A real
independent blind evaluation and H&M/security signoff remain separate
external obligations. Never turn green synthetic tests into pilot GO.

## Blind-cohort manifest cross-check (offline, structure only)

For independent evaluation, keep a **local, private** registration manifest
separate from the study's page transcripts. Run both tools on the authorized
host before interpreting any descriptive metric:

```text
python -m scripts.persian_ocr_blind_cohort_preflight --manifest /secure/local/cohort.json --measurements /secure/local/study.json
python -m scripts.persian_ocr_local_validation_metrics --input /secure/local/study.json
```

The manifest requires `schema_version: 1`, opaque `protocol_ref`, an
**operator-predeclared** `minimum_blind_holdout_sources`, at least one
`predeclared_critical_kinds` category, and `sources`. Each source has an
opaque `case_ref`, `source_file_sha256`, `split`
(`development` or `blind_holdout`), `source_kind`
(`native_scan`, `photograph`, `scanned_pdf`, `born_digital`),
`script_mix` (`persian` or `mixed_persian_latin`), and
`expected_critical_kinds`. Choose appropriate sample size and target
critical categories **before any evaluation**, with the qualified H&M study
owner. This utility does not choose thresholds for them or verify the
timestamp/freeze of those choices.

The cross-check refuses duplicate source hashes or case IDs (including
cross-split reuse), any metric page from the development split, unknown
source hashes, changed source-to-case bindings, and critical categories
outside those declared for the source. It reports only **aggregate** counts
for registered development/holdout sources, holdout sources with/without
pages, predeclared minimum coverage, and missing critical categories.
`submitted_holdout_structure_complete` is solely about **self-supplied
metadata completeness**, NEVER evaluation acceptance, independent
blindness, or real-case permission. All approval, expert signoff,
source-byte checking and semantic-accuracy flags remain `false`.

Do not store source scans, private references, reviewer identities, or the
manifest in the public repo. Both programs run locally and do not make
network calls; test fixtures are invented. This guard **cannot** detect
prior model exposure, unseen near-duplicates with different hashes, biased
sampling, assessor independence, correct transcription, or a false
operator declaration. Independent H&M and security oversight remains
mandatory and the pilot stays **NO-GO**.

## Local source-byte integrity check (does not authenticate file origins)

The manifest used in the blind-cohort check currently contains SHA-256
strings, which by themselves do **not** prove actual file integrity. On a
separately authorized offline study machine, prepare a **private**, local-only
inventory JSON:

```json
{
  "schema_version": 1,
  "files": [
    {"case_ref": "PRIVATE-OPAQUE-CASE-ID", "relative_path": "scans/file001.png"}
  ]
}
```

The inventory must contain exactly one row for **every** source registered in
the private `cohort.json` manifest, including development sources. Relative
paths are interpreted inside an approved `--source-root` directory; no
absolute paths, `..` traversal, symlinks or non-regular files are accepted.
Run:

```text
python -m scripts.persian_ocr_local_source_integrity --manifest /secure/local/cohort.json --inventory /secure/local/files.json --source-root /secure/local/source-files
```

The verifier streams each local file in bounded chunks, calculates SHA-256
from the bytes, and compares with that source's recorded hash. A changed,
missing, duplicate, misbound, symlinked, oversized or unreadable source fails
the entire invocation without printing a filename, source quote, identifier
or hash; successful output includes only aggregate file counts/byte totals
and `local_source_hashes_matched=true`. The inventory and source files
must remain **outside public CI / GitHub / connected storage**, and the
repository tests use only fictional tiny binary files. File limit is 256 MiB.
Use an appropriately protected machine and source store; this helper has
no network client and is not an evidence ingestion path.

**A local hash match proves only consistency between supplied local bytes
and the supplied SHA-256.** It does not prove chain-of-custody, trusted
enrollment, genuine original scans, source authorization, independent reviewer
adjudication, semantic OCR accuracy, or an unseen test set; none of these
claims may be inferred from `local_source_hashes_matched`. Source-file
integrity and measured accuracy remain different gates. The real claims
pilot remains **NO-GO**.

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
