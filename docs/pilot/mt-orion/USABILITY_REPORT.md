# Sprint 5 Phase C — MT ORION Claims Handler Usability Hardening Report

## Objective
Reduce avoidable Claim Handler effort identified in the Sprint 5A pilot without weakening Human-in-the-Loop controls, source attribution, or auditability.

## 1. AI Review workload
The MT ORION regression dataset contains **223 AI extraction candidates** across eight intelligence runs.

Deterministic evidence-unit grouping produces:

- **93 review groups** total;
- **24 repeatable row/line-item groups** (Engine Log, PMS, reported events, workshop findings/options, quotation/invoice line items);
- **22 groups flagged `Needs Attention`** by the exception rules;
- **130 fewer potential review actions** if each group is reviewed once rather than every field independently;
- **58.3% reduction** from raw field count to grouped review units.

The default UI is now exception-first. It initially shows judgment-heavy groups (unverified citations, warnings, confidence below 90%, opinions/inferences). Routine groups remain available and are not silently approved.

### Safety boundary
Grouped approval does not merge extraction records. Every field still receives its own human review status and append-only feedback/audit history. Field-by-field edit remains available for corrections.

## 2. Equivalent evidence
Document requirements can now expose approved Claim Facts as candidate alternative evidence. The first mappings are:

- Maker Recommendation -> `maintenance.recommended_overhaul_interval`
- Running Hours Record -> `maintenance.running_hours_since_overhaul`
- Last Overhaul Report -> `maintenance.last_overhaul_date`

No candidate is accepted automatically. The Claim Handler must provide a reason and explicitly choose **Accept as equivalent**. The requirement records the evidence basis, Claim Fact, reviewer and timestamp. If the direct document later arrives, it supersedes the equivalent-evidence state.

## 3. Workshop findings in Initial Assessment
The `Damage & Technical Findings` section now includes grouped human-reviewed Workshop damage findings rather than relying only on scalar equipment facts and rule issues. Source manifests link those statements back to the reviewed extraction records.

## 4. Preliminary vs final assessment UX
An approved preliminary version is now visibly labelled **Approved preliminary assessment — not final**. The UI instructs the handler to generate a new non-preliminary version after blocking evidence is resolved. A readiness-passed non-preliminary version is labelled as the final Initial Assessment.

## 5. Regression / QA
- Backend test suite: 111 tests passed at Phase C completion.
- MT ORION end-to-end regression: passed.
- PostgreSQL migration added: `0014_usability_hardening`.
- TypeScript/TSX source syntax: 20 files parsed with zero syntax errors.

## Remaining usability work
This phase does not claim a completed external usability study. Remaining design-partner work should measure actual handler time, error rate and interaction friction in-browser. Group editing is intentionally conservative: group approve/reject is supported, while corrections remain field-level.
