# HM-05 authoritative-source native rehearsal — 2026-11-01

This records an automated synthetic engineering observation, not a Persian OCR
fix, blind-holdout result, expert adjudication or customer-pilot acceptance.
The authoritative source is HM-05 in `cases.json` at application baseline
`fa2c471463f5aecb988f89e791aae359385227e4`, rendered with the existing
`make_upload_bytes` path. No alternate transcript or inferred negative is used.

[Machine evidence](validation/hm05-native-2026-11-01.json) binds the corpus bytes,
canonical case packet, actual original PNG, original/upload/storage hash, persisted
extraction hash, page 1/version 1 locator, native engine, pinned language-data
blobs and local toolchain. Checkout at execution was
`71f9257ad11ac104f4e472efe5d295bf60904e83`; its application/corpus are unchanged
from the main baseline. This is not a claim that #867's full Backend ran.

## Reproduction contract

Use only the existing invented corpus and an isolated test DB/Evidence root with
`APP_ENV=test`, `MCRI_SYNTHETIC_ONLY_CONFIRM=YES`, AI disabled and external
Evidence adapters off. Start the ordinary API, real document worker, web and
ClamAV. Never replace OCR with a supplied transcript or disable scan admission.
Provide a disposable synthetic bootstrap identity; keep its credentials private.

Install browser requirements using `tests/browser/requirements.lock`. Use the
existing `tests/browser/hm_multidoc_persian_ocr_e2e.py` with unchanged assertions.
For the native run, Playwright used system Chromium through its supported
`executable_path` option. No viewport, font, source, OCR assertion or quality guard
was altered. Set `OCR_ENABLED=true`, `OCR_LANGUAGES=eng+fas`, and a private local
`TESSDATA_PREFIX` containing the repository Dockerfile's exact traineddata:
commit `ced78752cc61322fb554c280d13360b35b8684e4`, with its recorded byte sizes
and Git blob checks verified before use. The evidence also records SHA-256s.
Native Tesseract was **5.5.0**, not the separately built production worker; rerun
the selected Docker runtime before any deployment-quality claim.

```bash
python tests/browser/hm_multidoc_persian_ocr_e2e.py
python -m unittest scripts.tests.test_hm_persian_ocr_probe -v
cd apps/api
python -m pytest -q tests/test_ocr_ai_review_original_source_guard.py
```

When using the installed system Chromium instead of Playwright's downloaded
browser, run the same harness from the repository root through this local adapter:

```python
import runpy
import sys
from playwright.sync_api import BrowserType

sys.path.insert(0, "tests/browser")
original_launch = BrowserType.launch

def launch(self, *args, **kwargs):
    if self.name == "chromium":
        kwargs.setdefault("executable_path", "/usr/bin/chromium")
    return original_launch(self, *args, **kwargs)

BrowserType.launch = launch
runpy.run_path("tests/browser/hm_multidoc_persian_ocr_e2e.py", run_name="__main__")
```

The browser harness renders the actual PNG, uploads all four sources through
authenticated manual intake, checks real clean scanning/processing, reads the
persisted source segment and source hashes, exercises literal lexical retrieval
and verifies the original-source warning/preview. It builds only a source-bound,
non-approved Preliminary Assessment. The script's historical `ci_only` report
label describes its allowed synthetic context; this observed run was local native.

## Actual result and limits

- Harness integrity/quality-label assertions passed in **10.257s** machine time.
  Four documents were clean and processed; one actual raster OCR segment had
  142 characters. Human task/review/rework time was not measured.
- Both machinery and negation literal `نیست` were present in this run. The
  **whole scoped negation clause was absent**, including when terminal punctuation
  was removed from the reference. Do not report this as the historical missing
  token recurring, or as a repair of #810. Engine/raster changes can change literal
  results; the exact measured byte hashes and versions must accompany comparisons.
- A second direct Tesseract execution on the stored original PNG exactly matched
  the persisted text hash. Original raster bytes matched the upload/storage hash.
  This places this run's whole-clause gap at OCR output rather than demonstrating
  persistence corruption. It does not establish semantic negation scope or full
  source-transcript accuracy; no transcript was corrected or inserted.
- Authenticated source inspection remained `machine_unverified` and
  `ocr_human_source_comparison_required`, page 1/version 1. The hold was not cleared,
  no fact was promoted by this rehearsal, and the Assessment was not approved.
- Ten existing original-source review-guard regressions passed in 23.62s.
  The combined read-only scanner/OCR literal-policy stdlib run passed 23 checks;
  those are separate from real OCR quality or professional approval.

No source text, rendered scan or complete transcript is copied into this report.
Hashes demonstrate this rehearsal's byte linkage, not authentic expert interpretation.
The public, already-used designated holdout cannot establish independent blinding.
Independent bilingual review of original scans, negation scope and unseen sources,
plus selected-host/OCR runtime acceptance, remains required. Keep #810 and related
source/PDF gates open; no external AI, customer data, production policy change,
coverage/causation decision or Pilot GO follows from this observation.
