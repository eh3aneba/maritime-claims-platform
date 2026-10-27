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

## One-command technical study runner (offline; no approval)

After the independent study owner has **separately** approved the source
permissions, blinded allocation, protocol and review responsibilities,
the local operator may run the same input files through all three
technical validations using **one process**:

```text
python -m scripts.persian_ocr_offline_study_run --manifest /secure/local/cohort.json --inventory /secure/local/files.json --measurements /secure/local/study.json --source-root /secure/local/source-files
```

It binds the same in-memory manifest to: (1) a streamed source-file SHA-256
comparison; (2) structural development/holdout split and declared coverage
checks; and (3) page-scoped literal OCR omission, insertion and conditional
search-gap measures. It **refuses to print any partial result** when a
source file, declared case, page coverage or typed reference input is invalid.
Successful stdout contains **aggregate counts only** and every
independent-approval and `pilot_accepted` field stays false.

The runner does not use external AI, make remote requests, persist source
text or supply an expert's judgment. Hashes remain self-declared until
independently witnessed custody is provided; comparing bytes to a manifest
does not prove authenticity. A syntactically complete study with high literal
recall cannot establish negation **scope**, causation accuracy or readiness
for live H&M claims. If the corpus has not been approved and adjudicated,
any local result is only a technical rehearsal, NOT validation evidence.

## Two-reviewer semantic disagreement ledger (self-reported observations only)

The literal-match study is insufficient to establish H&M source fidelity:
a recognized `نیست` may have moved to a different clause, reversing the
causation conclusion. A **separate local-only descriptive tool** supports
structured recording of two *reported* source-comparison judgments and
specialist escalation at each positive critical span:

```text
python -m scripts.persian_ocr_review_disagreement_metrics --manifest /secure/local/cohort.json --measurements /secure/local/study.json --reviews /secure/local/reviewer_observations.json
```

The private file uses `schema_version: 1`, a `protocol_ref` **identical
to the cohort manifest**, and `rows`. Each row references a declared
`case_ref`, `page_locator`, `span_ref`, `source_file_sha256` and
`extraction_sha256` from an existing *reference-positive* study span.
It contains `reviewer_one` and `reviewer_two` objects, each with a distinct
opaque `reviewer_ref` and one `finding` value:

- `meaning_preserved`: reviewer claims the phrase preserves the source
  **meaning and scope**; does not certify a correct OCR engine.
- `material_meaning_changed`: reviewer claims a material omission,
  substitution, negation scope, temporal or technical meaning error.
- `source_unreadable`: unreadable source or insufficient comparison.

The row's `specialist_adjudication` is **null** unless one reviewer
reports an error/unreadable source or their judgments differ. In those
cases it may contain a third, distinct `specialist_ref` and `finding`.
The instrument explicitly counts required, supplied and **missing**
specialist records, all reference-positive spans with no pair of review
rows, disagreements, reported material changes, unreadable source and
reported pairwise agreement. It **rejects duplicate/unknown/stale/misbound
spans**, undeclared fields and forged approval fields.

Use only pseudonyms; record actual authorization, signed independence,
review dates, reviewer notes, original visual page regions, professional
credentials, adjudicator rationale and disputes in a **separately controlled
evidence/audit system**, not in public GitHub or these aggregate-only logs.
Reviewer-ref inequality is **not proof of two actual people**. A supplied
specialist record is **not** authenticated specialist signoff. All
verification and pilot-acceptance flags are hardcoded **false**.
Keep real files and even private JSON observations on an approved offline
machine; synthetic test cases alone run in CI. An apparent 100% agreement
rate never authorizes critical causation or coverage extraction.

## Experimental local Tesseract page-segmentation ablation (no production change)

The actual image-only HM-05 regression has shown that a successfully
processed document can omit `نیست`. Instead of switching OCR engines
based on guesswork, an optional **real Tesseract invocation** compares
the **same PNG bytes** under page-segmentation modes 3 (the current
Tesseract default), 4, 6 and 11. The experiment uses `eng+fas` and
tests four exact probes: the machinery term, the negation token,
the entire qualified negation clause **including punctuation**, and
the incident date. Separately it checks qualified clause wording
**without only terminal punctuation**; neither wording test proves
that the negative clause is correctly applied to the right fact. It **does not** reconstruct
missing text, repair OCR, write to the claims system, modify the
production worker, or declare a successful semantic extraction.

On an isolated local machine with the existing project's Chromium
Playwright setup and Tesseract installed with `eng` and `fas` data:

```text
python -m scripts.persian_ocr_tesseract_psm_ablation --fixed-synthetic-hm05
```

This generates the existing fictional HM-05 PNG with Chromium **in
memory**, invokes local Tesseract in a temporary directory, and prints
only four mode records with critical literal-presence booleans. No OCR text,
original phrase, source path, identifiers, screenshot, or Tesseract
stderr is printed. This is a public engineering probe, **not** a
blinded holdout or verified quality study; the real run must be executed
explicitly on a machine with Tesseract and Playwright. The **CI unittest
only tests command/privacy/error behavior with a mock engine**; it does
not claim that a real OCR comparison was run.

For a separately authorized private PNG, use:

```text
python -m scripts.persian_ocr_tesseract_psm_ablation --image /secure/local/source.png --reference /secure/local/three_probes.json
```

The private reference JSON must contain `schema_version: 1`,
`source_file_sha256` (calculated from the image bytes) and exactly
four `probes`: `machinery_term`, `negation_token`,
`negation_clause`, and `incident_date`, each with a nonempty `literal`. The negation
token must occur literally inside the reference full clause.
Reference data stays offline and must come from authorized source
reviewers; a valid JSON shape is not expert approval. This prototype
accepts **PNG only**, limits input size and OCR runtime, and fails
closed if any mode errors rather than publishing partial observations.

### Observed local synthetic HM-05 diagnostic (not independent evaluation)

A **real local trial** (Tesseract 5.5.0 with `eng+fas`, Chromium
rendering with Noto Sans Arabic, the existing fictional HM-05 wording)
found that the unchanged original PNG failed to recover the standalone
`نیست` across PSM 3, 4, 6 and 11. In a separate exploratory
**11-image-variant × 3-PSM = 33-setting sweep**, 21/33 outputs contained
the standalone negation token. This is **not** 21/33 different scans,
nor a sensitivity or recall estimate. The complete punctuation-exact
negative clause was missing in all 33 outputs; that metric is strict
and affected by sentence-final punctuation. Under 2× grayscale scaling
and PSM 6, the core negation-clause wording appeared without its final
period, **but the same OCR output changed the incident-year digits**.
Therefore this experiment uncovered a potentially useful candidate
and a simultaneous *critical temporal regression*; it did **not**
demonstrate a safe OCR fix.

These observations were performed on the assistant's isolated Linux
environment, **not the pinned production worker image**, and have
not been independently rerun or signed off. There are no customer
files or expert labels in the study. The versioned script here allows
replication and now reports negative-clause punctuation-sensitive,
punctuation-free core, and incident-date checks separately. Do not
treat a token recovered on one synthetic image as accuracy evidence.

**Do not pick a winning PSM from lexical presence alone.** Recognizing
a standalone `نیست` does not demonstrate its position or semantic
scope in the causal sentence. Identical pages can behave differently
under fonts, scans, rotations and marine terminology. Keep the current
worker and safety flags unchanged. If an experiment reveals a candidate
with better *complete-clause* retrieval, replicate on a separate
permission-cleared, blind and independently adjudicated cohort and
compare critical-span misses and false insertions **before** any
processing-code change. The pilot remains **NO-GO**.

## Reproducible real synthetic OCR on a fresh GitHub runner

`.github/workflows/persian-ocr-real-synthetic-probe.yml` now runs
**actual** Tesseract with installed `eng`/`fas` language data over the
same fixed public HM-05 image generated by Playwright/Chromium. It is
available on changes to its own workflow or PSM/fixture sources, and via
manual `workflow_dispatch`. It accepts **no user-supplied scans or
runtime source paths**. The runner uses an isolated, temporary
environment; it does not modify the OCR worker or send documents to
external AI.

The job records only bounded yes/no observations for PSM 3, 4, 6 and 11
in the GitHub Actions **job summary**: machinery term, negation token,
negation-clause core, punctuation-exact clause, and incident date.
Raw Tesseract output and the image are not included in the summary or
uploaded as artifacts. Failed extraction or invalid report structure
fails the job without a partial-success claim. A **green** run means
only that the measurement harness executed successfully, **not** that
the OCR recognized the source accurately. The summary explicitly
labels this as an engineering diagnostic and the pilot as NO-GO.

The GitHub Ubuntu package versions and font rasterization may differ
from the pinned production OCR worker. Exact comparability would require
a separately attested production-equivalent environment and controlled
image/source digests. This workflow **is not** an independent unseen
scan test, a reference-transcript study, or a human reviewer signoff.
The public synthetic HM-05 is deliberately not used as a blind
acceptance cohort.

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
