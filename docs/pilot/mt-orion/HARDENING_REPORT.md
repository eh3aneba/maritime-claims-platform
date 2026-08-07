# Sprint 5 Phase B — MT ORION Pilot Hardening Report

## Executive result

All three P0 findings from the Phase A internal pilot are closed in the regression case. The MT ORION workflow now preserves Chief Engineer narrative event timing, retains events with no stated clock time as relative/undated evidence, correctly classifies passive shutdown wording, deduplicates same-statement event candidates, and no longer sums alternative quotations into claim exposure.

**P0 findings remaining: 0**

## Regression outcome

| Metric | Hardened result |
|---|---:|
| Uploaded documents | 9 |
| Structured AI runs | 8 |
| Candidate extraction rows | 223 |
| Human-approved scalar claim facts | 29 |
| Active chronology events | 7 |
| Open chronology conflicts | 1 |
| Shutdown conflict | 20 minutes / Medium |
| Active technical issues | 2 |
| Active document requirements | 9 |
| Critical outstanding/requested documents | 2 |
| Derived financial cost items | 7 |
| Open financial flags | 3 |
| Reviewed invoiced/claimed cost | USD 25,000 |
| Quotation alternative A | USD 260,000 |
| Quotation alternative B | USD 470,000 |
| Reserve | USD 575,000 |
| Initial Assessment readiness | 72% / Not Ready |
| Assessment | Approved Preliminary v1 |

## P0-01 — Alternative quotation double-counting

### Before
Initial Assessment added:

- Quote A: USD 260,000
- Quote B: USD 470,000
- Invoice: USD 25,000

and displayed USD 755,000 as reviewed cost exposure.

### After
Initial Assessment now shows:

- **Reviewed invoiced/claimed cost: USD 25,000**
- **Accepted cost: none recorded**
- **Paid cost: none recorded**
- Quotation alternatives individually:
  - Global Turbo Marine Q-B-470 — USD 470,000
  - Ocean Turbo Services Q-A-260 — USD 260,000

The section explicitly states that quotation alternatives are **not cumulative claim exposure**.

**Status: CLOSED**

## P0-02 — CE narrative event timestamps

Chief Engineer Report schema is now v2 and includes `reported_events[]`.

The pilot chronology now records:

- 10:30 — Abnormal machinery condition observed
- 10:40 — Engine load reduced
- approximately 10:45 — Main engine shutdown
- 10:52 — Engine Log machinery alarm
- 11:05 — Engine Log main engine shutdown
- 11:12 — Engine Log machinery isolation
- Relative / time not stated — CE Report machinery isolation

The CE isolation statement no longer inherits `incident.time=10:30`.

The legitimate shutdown difference is now:

**10:45 CE narrative vs 11:05 Engine Log = 20 minutes / Medium conflict**

instead of the artificial 35-minute High conflict.

**Status: CLOSED**

## P0-03 — Passive shutdown classification and duplicate candidate generation

Deterministic chronology classification now recognizes forms including:

- `engine was stopped`
- `main engine was stopped`
- `engine has been stopped`
- `engine stopped`
- `stopped the engine`
- `ME was stopped`

When CE v2 `reported_events[]` exists, chronology does not create duplicate event candidates from `immediate_actions[]` and operational-impact booleans. A same-source-statement deduplication guard also remains in the clustering layer.

**Status: CLOSED**

## Remaining P1 backlog

The original P1 findings remain valid and should drive the next product-hardening work:

1. Reduce human-review volume with row/table-level review workflows.
2. Allow document requirements to be provisionally satisfied by equivalent reviewed evidence.
3. Use reviewed Workshop damage findings more fully in Initial Assessment.
4. Clarify `Approved Preliminary Assessment` vs final/ready terminology in UX.
5. Implement Claim Notification automated intake / Create Claim from Document.

## Validation performed

- Full Backend suite: **105 passed**
- MT ORION regression pilot: **passed**
- Python compilation: passed
- PostgreSQL Alembic upgrade through `0013_pilot_hardening`: passed in offline SQL generation
- PostgreSQL downgrade `0013 -> 0012`: passed in offline SQL generation
- Frontend TypeScript/TSX syntax: **20 files, 0 syntax errors**
- `git diff --check`: passed

## Pilot readiness verdict

**P0 technical hardening: PASS**

The product can now proceed to usability hardening and design-partner preparation. This is not yet a claim of production readiness: live model quality, real OCR, concurrent PostgreSQL runtime, full browser E2E, malware scanning and real customer workflow validation remain outstanding.
