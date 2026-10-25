# R5 — Six versioned *invented* H&M machinery multi-document cases (v1.0.0)

This corpus converts the 25 October 2026 corrective plan into an actionable
**product journey** test without real insurer Evidence or external model inference.
It supplements, but does not replace, the existing nine-document synthetic
MT ORION pilot and the three short local-Qwen source-quote experiments.

**Exactly six cases / 25 source documents**, with distinct attributed
sources and explicit version metadata:

| Case code | Split | Intentional source challenge | Documents |
| --- | --- | --- | ---: |
| HM-01 | development | reported casualty, engineer, log and PMS records | 4 |
| HM-02 | development | requested-but-not-supplied engine/PMS evidence | 4 |
| HM-03 | development | engineer vs workshop alarm-time conflict | 4 |
| HM-04 | development | superseded engineering statement and corrected v2 | 5 |
| HM-05 | *designated holdout* | Persian image-only machinery report, genuine raster OCR pending exercise | 4 (one PNG) |
| HM-06 | *designated holdout* | competing USD/EUR quotations and separate inspection invoice | 4 |

The single machine-readable source is `cases.json`; **these are invented
narratives, not anonymous customer documents**. All source lines are
deliberately framed as reports, statements, log *extracts*, unknowns or
unverified records. Financial proposals are not paid invoices. No case
contains a machine-authored expert answer, scored reference, claims coverage
decision, insurer liability conclusion or approval flag. The 4/2 split
is designated now, but true held-out blindness needs restricted access to
model/prompt development and independent reviewers; a public GitHub repo
alone cannot enforce it.

## HM-04 actual replacement/source-freshness acceptance (new)

`tests/browser/hm_multidoc_replacement_e2e.py` executes a **second**
disposable, authenticated, wholly synthetic product journey in the
protected browser CI. Four actual DOCX files are admitted and processed,
including the v1 engineer statement. A source-bound v1 Initial Assessment
is generated, then the actual authenticated `/documents/{id}/replacements`
API admits the corrected engineer report as **v2** with a recorded reason.

The acceptance rejects a broken family/supersedes/version/file-hash
chain, checks that the old Document remains readable in metadata but
`is_current=false` and bytes/hash preserved, and that attempting to
write a review to the stale v1 Assessment returns **409**. A further
attempt to replace the superseded old version must also return **409**.
After real malware scan / worker processing of v2, a new preliminary
v2 Initial Assessment must have a **different bound source fingerprint**
and cite the *current* engineer v2 plus the other three current sources
without citing superseded engineer v1. The UI must still render both
document versions and the Initial Assessment workspace; history must
mark v1 stale and v2 current.

To enforce this semantic boundary, the new Initial Assessment
`Documents Received` projection excludes `is_current=false`
document rows. Historical source fingerprints continue to include
non-deleted older versions via the separate source-integrity snapshot;
**no original source or chronology audit is deleted**. The prior
`HM-01` journey is retained unchanged and runs first.

CI measures only machine elapsed stage time, not handler productivity.
The script never calls a model, writes a real claim or records
pretend expert approval. Historical records may remain available to
authorized humans; excluding them from a *new/current* assessment
does not erase the old immutable assessment version. **Pilot GO=NO.**

## HM-05 genuine Persian OCR — processing proof and open quality defect

`tests/browser/hm_multidoc_persian_ocr_e2e.py` exercises the real,
authenticated **local** worker and Tesseract, with an image-only PNG
rendered from the fixed invented Persian source through Chromium.
Four documents must be admitted, malware-clean and processed; the
persisted PNG extraction must report `tesseract:eng+fas`, positive
char/segment counts, a document-bound text hash and page locator.
The generated Initial Assessment remains **preliminary/unapproved**.

**Observed on the previous CI head**: The complete original test
failed in real browser run [#40207012936](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/40207012936)
because a source phrase could not be retrieved despite successful
OCR processing. Independent reproduction of the synthetic raster
showed the technical equipment term `توربوشارژر` recovered, while
the visually present line containing `نیست` was omitted by Tesseract.
This is a **material OCR negation-quality failure**, now tracked in
[Issue #810](https://github.com/eh3aneba/maritime-claims-platform/issues/810),
not a successful two-phrase acceptance result.

This protected browser regression now asserts real OCR/locator evidence
for the **technical equipment term** and *records* the negation probe
outcome. If missing, `critical_negation_omission_observed=true`,
`negation_retrieved=false`, `quality_disposition=negation_missing_review_required`
and `both_literal_probes_retrieved=false` are written to a bounded
synthetic CI artifact. No missing word is constructed, guessed or used
as an extracted fact. Even if both literal probes are observed, the
result remains **machine-unverified** and `negation_scope_verified=false`,
`human_bilingual_review_required=true`,
`critical_fact_authorization_granted=false` and
`pilot_accepted=false`. A green CI after this revised check proves
**safe omission reporting and system integration**, not semantic OCR
accuracy, not that negation was recovered. The independent bilingual
original-vs-transcript comparison remains open and **quality NO-GO**.

There is no external model, no customer evidence, no human source
approval and no cover/causation/payment decision in this test. Future
work must measure Persian critical negation/time/term accuracy on
separately controlled unseen scans and remediate [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810).
Do not silently waive that independent quality gate to ship a pilot.

HM-05 was designated a holdout at corpus creation, but its source
phrases now inform regression engineering in a public repo; **it is
not a sealed blind LLM holdout**. A fresh independently held evaluation
set is required.

## HM-06 actual financial *source intake*, no AI or invented quantum

`tests/browser/hm_multidoc_financial_intake_e2e.py` exercises the
protected, disposable **AI_PROVIDER=disabled** stack with HM-06's
four invented documents. It creates an authenticated unique tanker
claim in TRIAGE and uploads four real DOCX files through the same
manual Evidence API: a notification, **two mutually alternative**
repair quotations (one described in USD and another in EUR), and a
separate **inspection invoice whose payment status is unknown**.
ClamAV must mark all four CLEAN and the real worker must process them.

Because no independent AI extraction and no human financial cost
review have occurred, **there must be no derived CostItems,
quotation comparison valuations, per-currency amount totals, paid
invoice amount, reserve or settlement authority** in the backend
financial-review response. The client Financial review page now
also fetches the *tenant-scoped existing document inventory* and
separately displays current typed quotation/invoice **source file names,
document versions, scan statuses and processing statuses** even
before any reviewed line items exist. The assigned upload type is
not proof of a correct type, scope, currency, amount, incurred cost or
legal coverage. Superseded document versions are not represented
as current. Quotation alternatives are never added together in
this intake-only view; the invoice is never marked as paid.

The browser test asserts the two quote rows + one invoice row are
visible, checks no document-embedded fictional amounts were promoted
to on-screen financial valuations, and writes only code-owned source
counts plus machine-observed stage times to a bounded CI artifact.
**The test does not assess real claim quantum, verify exchange rates,
prove costs were incurred, choose repair suppliers, approve a reserve,
or measure handler productivity.** No external AI model or customer
Evidence is accessed. A separate independent bilingual/H&M
human-reviewed benchmark and explicit cost-document evidence
verification remain required; real pilot **NO-GO**.

## Actual uploadable fixtures — no fake text-extension upload

`scripts/hm_multidoc_packs.py` validates the finite in-repo source
schema and renders valid OOXML **DOCX bytes in memory** using Python's
standard library. The Persian source in HM-05 is rendered to an
**image-only PNG** by Chromium/Playwright with RTL text using the same
approach as the existing `intake_maturity_e2e.py`; no OCR transcript is
substituted for image processing. `source_version=2` plus
`replaces_source_id` describes HM-04's *intended* version lineage;
actual backend `/replacements` upload and audit are **not claimed to
have run** until a dedicated integration exercise verifies them.

A static and simulated-data-only offline suite validates all 25
document/source IDs, versions and splits, rejects malformed or forged
fields, and verifies DOCX zip/XML round-trips. It neither invokes
Qwen/Ollama nor approves a human reference.

```bash
python -m unittest scripts.tests.test_hm_multidoc_packs -v
```

## Real synthetic browser path — HM-01 only

The protected CI browser job starts the existing **isolated disposable
test stack** with ClamAV, PostgreSQL, worker and AI_PROVIDER=disabled.
After ordinary demo login the new
`tests/browser/hm_multidoc_journey_e2e.py` exercises:

1. Create a distinct invented vessel and claim in the test organization.
2. Upload one real DOCX via the handler's **browser file input** and the
   next three through the *same authenticated manual document-upload
   HTTP endpoint* (never external email/SFTP/Drive).
3. Require four actual ClamAV CLEAN documents and successful worker
   processing, with source/version/hash metadata preserved.
4. Display the Initial Assessment UI and generate an intentionally
   **preliminary, unapproved** assessment from the real current claim
   state; verify all four persisted document IDs appear in the
   assessment's source manifest and its fingerprint is present.
5. Visit Claim Pack Export UI, create a review-aid Excel snapshot,
   retrieve its bytes and verify the two advertised immutable hashes.

The test persists a bounded JSON report at
`artifacts/hm-six-pack-browser-journey.json` with **only code-owned case
ID, machine-observed stage durations/counts and FALSE human/LLM/pilot
approval flags**. Existing CI artifact retention applies. The report
contains no claim UUID, test credentials, model prose or actual source
content. The test is **fail-closed** unless APP_ENV=test,
MCRI_SYNTHETIC_ONLY_CONFIRM=YES, AI_PROVIDER=disabled and both endpoints
are literal 127.0.0.1; never run it on a real customer host.

**Honest current scope:**
- Automated CI does *not* measure the handler's reading, review, correction
  or correspondence time; those require a genuinely observed usability
  exercise with independent human operators.
- HM-02 through HM-06 are **corpus sources only**, not yet six proven UI
  workflows. The replacement and Persian OCR cases remain explicit
  pending integration exercises.
- This does not introduce an approved local LLM gateway; manual/rules
  baseline and independent H&M specialist blinded reference still
  require real human review before any Qwen task-quality decision.
- Browser checks may PASS while independent host installation, matched
  DB+Evidence restore, historical secret findings, model egress and
  customer permission remain UNVERIFIED.

**Pilot GO=NO.** See the live
[execution status](../../roadmap/SEECLAIMS_V1_EXECUTION_STATUS.md)
and #647, #752, #653, #764. No actual customer data is authorized.
