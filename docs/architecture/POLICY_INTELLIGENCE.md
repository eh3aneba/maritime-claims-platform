# Policy & Contract Intelligence

## Purpose

Policy & Contract Intelligence converts extracted policy/contract text into
source-linked review candidates and, after explicit Human Review, a structured
term register and explainable issue spots. It supports a qualified claims
handler or lawyer; it does not determine coverage.

## Supported reviewed terms

- policy period, attachment and expiry
- insured/agreed value and limits
- percentage, fixed and minimum deductible/excess wording
- notice requirements and time limits
- governing law, jurisdiction and arbitration
- clauses, extensions, exclusions, warranties and conditions
- classification and maintenance obligations
- General Average, collision, Sue and Labour, salvage/towage,
  pollution/wreck-removal and war-risk wording

## Local candidate extraction

The initial extractor is deterministic and local. It reads existing
`DocumentTextSegment` records produced by the secure document-processing
pipeline. Keyword and value patterns create `DocumentExtraction` candidates
with:

- exact source quote
- page/sheet/document locator
- structured normalized value where safely parseable
- confidence and validation warnings
- pending review status
- an auditable local `AIRun` whose provider is `deterministic_local`

No external AI receives evidence. Unsupported wording remains a manual-review
responsibility.

## Human-review boundary

Policy and contract paths are permanently non-promotable to ordinary
`ClaimFact` rows. Approve/Edit/Reject uses the existing append-only
`AIFeedback` and source-aware review workflow, but approved values feed the
Policy Term Register instead of the casualty fact store.

Replacement policy documents never inherit review state. Terms from superseded
sources remain visible with a prominent re-review issue.

## Issue spotting

The read model produces review prompts for:

- missing current policy wording
- missing reviewed policy period, deductible or insured value/limit
- incident date potentially outside extracted period
- recorded notification potentially later than an extracted day-based deadline
- exclusions and warranties requiring claim-specific legal/factual analysis
- time limits requiring human calculation and diarising
- missing governing-law/dispute-resolution terms
- reviewed terms attached to superseded sources

Every prompt carries its deterministic trigger and a required human action.
The service never applies an exclusion, warranty, deductible or time bar and
never outputs covered/not covered.

## Tenant and version controls

All reads and extraction requests enforce organization, claim and document
scope. Extraction accepts only current, active documents classified as a
supported policy/contract type and requires completed text extraction/OCR.

## Known limitations

- pattern extraction is intentionally conservative and English-first
- complex schedules, endorsements and incorporated wordings require manual review
- dates and deadlines are review triggers, not legal calculations
- issue spotting does not evaluate prejudice, waiver, proximate cause,
  anti-technicality rules or governing-law remedies
