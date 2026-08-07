# Sprint 5 Phase A - MT ORION End-to-End Pilot Report

## Executive result

The synthetic MT ORION case completed the current MVP workflow from claim creation through an approved **preliminary** Initial Assessment. The architecture held together across evidence, AI candidate data, human review, deterministic rules, chronology, technical review, financial review, tasks, reserve history and assessment versioning.

The pilot also exposed several material gaps that should be fixed before an external design-partner pilot. The most important are chronology timestamp semantics and financial exposure aggregation.

## Observed pilot metrics

| Metric | Observed result |
|---|---:|
| Uploaded documents | 9 |
| Structured AI runs | 8 |
| Candidate extraction rows | 205 |
| Human-approved scalar claim facts | 29 |
| Active document requirements at Financial Review | 9 |
| Critical outstanding/requested documents | 2 |
| Important missing documents | 1 |
| Active deterministic technical issues | 2 |
| Active chronology events | 8 |
| Open evidence conflicts | 2 |
| Derived financial cost items | 7 |
| Open financial flags | 3 |
| Reserve history entries | 1 |
| Open rule-driven document tasks | 2 |
| Initial Assessment sections | 11 |
| Initial Assessment readiness | 72% / Not Ready |
| Assessment | Preliminary v1, human reviewed and manager approved |

## What worked as intended

### Evidence and processing

All nine DOCX/XLSX fixtures passed upload validation, secure storage, text extraction and source segmentation. The eight supported intelligence document types produced structured runs without external AI connectivity.

### Human-in-the-loop boundary

The Running Hours fixture states **"No approved extension on file"**. The deterministic fixture AI intentionally produced an over-confident boolean candidate `interval_extension_approved = false`. Human review rejected it because the wording proves only that no approval is in the file, not that no valid extension exists elsewhere. No authoritative Claim Fact was created from the rejected candidate.

This is a useful validation of the product's core principle: AI candidate data does not become claim truth automatically.

### Rules and missing evidence

The reviewed running-hours and PMS evidence triggered:

- `TECH-001` - Possible overdue maintenance
- `TECH-003` - PMS indicates deferred maintenance

The system did **not** convert either flag into causation.

At Financial Review, the active critical missing evidence was:

- H&M Policy / Wording - requested
- Last Overhaul Report - requested

Maker Recommended Overhaul Interval remained an Important missing document even though an interval value was present in the Running Hours Record.

### Task workflow

`Request All Critical` created two auditable rule-driven tasks and a document-request draft. The requirements only moved from Missing to Requested after explicit human confirmation that the request had been sent externally.

### Financial intelligence

Financial Review correctly identified:

- Invoice predates reported casualty
- Material quotation scope difference
- Potential betterment / upgrade cue for the upgraded controller

The invoice-only reviewed total was correctly calculated as **USD 25,000**.

### Reserve and assessment

A USD 575,000 reserve entry was appended to Reserve History. Because critical evidence remained outstanding, a non-preliminary assessment was correctly blocked. An explicitly overridden Preliminary Assessment was generated with all 11 sections, reviewed section by section and manager-approved.

---

# Pilot findings / hardening backlog

## P0-01 - Initial Assessment double-counts alternative quotations

**Observed:** The Financial Review correctly reports invoice exposure of USD 25,000, but the Initial Assessment Financial Exposure section totals all `cost_items`, including both alternative quotations plus the invoice:

`USD 260,000 + USD 470,000 + USD 25,000 = USD 755,000`

This is misleading because Quote A and Quote B are alternative repair scopes, not cumulative incurred/claimed expenditure.

**Required fix:** Separate at least:

- Quoted alternative exposure
- Claimed/invoiced cost
- Accepted cost
- Paid cost

Initial Assessment must never sum mutually exclusive quotation options into the claim exposure total.

**Priority:** P0 / must fix before external pilot.

## P0-02 - CE narrative action timestamps are lost in Chronology

**Observed:** The CE Report states first abnormality at 10:30, load reduction at 10:40, shutdown at approximately 10:45 and later isolation. The current CE schema stores only one `incident.time`, and Chronology assigns that single 10:30 time to all CE immediate actions.

This generated artificial conflicts against the Engine Log:

- Shutdown: CE-derived 10:30 vs Engine Log 11:05 -> 35-minute High conflict
- Isolation: CE-derived 10:30 vs Engine Log 11:12 -> 42-minute High conflict

The actual CE shutdown wording is approximately 10:45, so the system is manufacturing precision by reusing the incident timestamp.

**Required fix:** CE Report extraction needs timestamped narrative events, e.g. `reported_events[]` with date/time/timezone/action/source. If an action has no explicit timestamp, Chronology must preserve it as undated/relative rather than assigning `incident.time`.

**Priority:** P0 / must fix before relying on chronology conflicts.

## P0-03 - Chronology phrase classification misses passive shutdown wording

**Observed:** `The main engine was stopped at approximately 10:45 UTC` was classified as a generic `action` because the deterministic phrase matcher recognizes `engine stopped` / `stopped engine`, but not `engine was stopped`.

A separate `operational_impact.engine_stopped=true` created another shutdown candidate, so the same narrative produced both a generic Action and a Shutdown at 10:30.

**Required fix:** Expand deterministic action taxonomy and deduplicate event candidates derived from the same source statement.

**Priority:** P0/P1.

## P1-01 - Human review volume is too high

**Observed:** Eight AI documents produced **205 candidate extraction rows**. Reviewing every Engine Log/PMS/financial field individually is too slow for a claims handler.

**Required UX:**

- Review/approve an Engine Log row as a unit
- Review PMS job rows as a unit
- Review quotation/invoice line items as a table
- Preserve field-level audit underneath
- Highlight only low-confidence, conflicting or decision-sensitive fields

**Priority:** P1; likely essential for pilot usability.

## P1-02 - Document requirements cannot recognize alternative/equivalent evidence

**Observed:** `Maker Recommended Overhaul Interval` remains Missing because no document with type `maker_recommendation` exists, although a human-approved 12,000-hour maker interval is present in the Running Hours Record.

The conservative behavior is safe but can create unnecessary requests.

**Required fix:** Support requirement states such as `Provisionally satisfied by alternative evidence`, with explicit source and human approval, rather than treating document type as the only satisfaction mechanism.

**Priority:** P1.

## P1-03 - Damage section underuses reviewed Workshop findings

The Technical Review Matrix contains Workshop findings and source opinion evidence, but the Initial Assessment `Damage & Technical Findings` section primarily uses scalar facts and Rule Issues. Detailed reviewed damage findings should be summarized explicitly with source links.

**Priority:** P1.

## P1-04 - Approved Preliminary terminology may confuse users

A manager can approve a Preliminary Assessment while Readiness remains `Not Ready`. This is valid as an internal workflow state, but UI wording should distinguish:

- `Approved Preliminary Assessment`
- `Final / Ready Assessment`

from any suggestion that the claim itself is approved.

**Priority:** P1 UX.

## P1-05 - Claim Notification is not yet an automated intake path

The pilot still creates the claim manually. `Create Claim from Document` and generic initial document classification are PRD capabilities not yet implemented.

**Priority:** P1 after P0 hardening.

---

# Known validation limits

This pilot is deliberately deterministic. It validates application orchestration and domain logic, not model quality under real-world uncertainty.

Not yet validated here:

- Live external LLM responses
- Scanned PDF / OCR quality
- Messy real engine-room logs
- Very long multi-document claims
- Real PostgreSQL runtime under concurrent users
- Full Next.js browser E2E build/run
- Malware scanning
- Customer-specific policy wording / coverage intelligence
- External email integration

## Pilot verdict

**Architecture: PASS** - the current layers integrate successfully end to end.

**External pilot readiness: NOT YET** - fix P0 chronology and financial aggregation issues first, then run a hardening/regression pass before exposing the workflow to a design partner.
