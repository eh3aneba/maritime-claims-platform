# Design Partner Pilot Protocol v1.0

## Current authorization boundary — 31 October 2026

**Pilot v1 with real customer claim evidence: NO-GO.** This protocol permits
*discovery and usability rehearsal with fictional/synthetic H&M machinery
claims*, not permission to onboard real case files or claimants. Historical
engineering CI results are not independent OCR accuracy, local-model, security
or operator sign-off. The controlled real-data Pilot v1 must meet the
[scope and operational Definition of Done](https://github.com/eh3aneba/maritime-claims-platform/issues/647)
and the explicit release-candidate gates in `scripts/pilot_rc_gate.py`.

- First release candidate: **one H&M machinery-claims handling team**, with
  authenticated manual evidence upload only. SFTP, email and Drive ingestion
  remain **OFF** unless separately authorized; a real SFTP acceptance
  exercise is only required if SFTP is deliberately enabled.
- **AI is disabled by default.** The self-hosted Ollama/Qwen development
  smoke is strictly synthetic and is **not** a validated production inference
  integration. Do not send any real documents or customer facts to local or
  external AI based on a green synthetic test. Issue
  [#752](https://github.com/eh3aneba/maritime-claims-platform/issues/752)
  requires independent model, source and human-review acceptance first.
- Persian OCR may omit a material negation. An extracted phrase, nonempty
  transcript or successful retrieval is not semantic verification. See
  [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810).
  Original-source bilingual human verification remains mandatory for any
  critical Persian narrative, date/time, causation or machinery assertion.
- An unresolved source discrepancy is an **unverified operator report**.
  Historical AI facts/assessments and Claim Packs can require revalidation
  without changing the earlier human decision; see
  [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850).
- Discovery participants may evaluate the fictional UI journey, missing
  evidence, chronology, manual decisions, versioned assessment and exports
  without activating AI. Record unsupported or unmeasured capabilities as
  **not measured**, never as accepted.

A named design partner, explicit documented data authorization, operator
readiness evidence, security/privacy assessment and formal Pilot GO decision
are separate prerequisites for any real-data exercise. No customer evidence
may be used merely because a participant volunteers a file.

## Purpose
Validate whether MCRI creates measurable workflow value for marine claims teams and whether that value can become a real buying process. A successful session must produce evidence, not compliments.

## Participant profile
Prefer one operational user and one economic/managerial stakeholder across the validation cycle:
- Claims Handler / Senior H&M Claims Handler — workflow, evidence quality, trust.
- Claims Manager / Head of Marine Claims — portfolio value, approval, buyer/champion map.
- Optional IT/Security stakeholder only after value is demonstrated.

Do not begin with the largest or most complex enterprise. A medium marine insurer, ship manager, or P&I correspondent with frequent machinery claims is a better first design partner.

## Before the session
1. Confirm the participant handles or supervises H&M machinery claims.
2. Record a manual baseline from a comparable workflow: minutes to first structured assessment.
3. Keep the first task fictional: use the synthetic MT ORION dataset. Do not use any anonymized/shadow real claim unless the separate real-data pilot authorization gates above have been completed and documented.
4. Do not disclose target KPI thresholds to the participant before the task.
5. Do not lead with a list price before asking how the current process is budgeted and what a credible paid next step would be.

## Session structure — 60 to 75 minutes
### 0–10 min — Context and baseline
Ask how the claim would be handled today, which systems are used, who reviews it, and how long the first assessment normally takes. Record the baseline rather than debating it.

### 10–40 min — Controlled product task
Participant should independently:
- find/open the claim;
- identify missing critical evidence;
- review manually governed source evidence and provenance; evaluate AI suggestions **only** if the separate local-AI acceptance gate has actually been approved;
- inspect chronology/conflicts;
- review technical issues;
- compare commercial evidence;
- read the preliminary assessment;
- identify next actions.

Facilitator should not coach except when the participant is blocked by an obvious navigation defect. Record friction when help is required.

### 40–50 min — Product debrief
Capture:
- what was faster;
- what was harder;
- where the participant distrusted the system;
- false positives / false negatives;
- must-have changes before live use;
- user rating 1–10.

### 50–65 min — Commercial interview
Record buyer, champion, budget owner, deployment preference, security blockers, annual claim volume, pricing model preference, willingness-to-pay signals, and buying timeline. Use `COMMERCIAL_VALIDATION_FRAMEWORK.md`.

### 65–75 min — Commit a next step
A valid commercial next step should be concrete, for example:
- security review with named IT owner;
- paid pilot proposal;
- second pilot on customer-anonymized claims;
- business-case meeting with Head of Claims;
- procurement introduction.

"Send me more information" is not a strong next step unless it has a named owner and date.

## Product success targets — internal pilot thresholds
- AI acceptance rate: >= 80% **only after independent AI acceptance and an actually measured sample**; otherwise record Not measured.
- Time to first assessment reduction: >= 30% against recorded baseline.
- Missing-document precision: >= 90% when enough items were explicitly validated.
- User rating: >= 8/10.
- Critical product feedback: 0 unresolved critical items before expanding the pilot.

These are validation thresholds, not marketing claims.

## Commercial validation signals
Strong signals:
- named buyer and champion;
- a budget source or credible path to one;
- explicit willingness to pay for a pilot or annual product;
- concrete next step with owner/timeline;
- security/deployment requirements that are difficult but feasible.

Weak signals:
- "interesting";
- requests for a generic brochure;
- feature wishlists without a buying path;
- praise from a user who cannot identify who would pay.

## Go / Pivot / Stop interpretation
- **GO**: product-value targets are not failing and there is buyer + champion + WTP + next-step evidence.
- **PIVOT**: interest exists but product trust/value or the buying case is incomplete. Change workflow, ICP, packaging, or commercial motion before scaling.
- **STOP**: the individual session records explicit no interest with no WTP or follow-up signal. Treat this as a session-level result; stopping the company/product should require repeated evidence across relevant design partners.
- **INSUFFICIENT_DATA**: do not force a decision when the evidence is missing.

## What not to monetize yet
For early ROI, monetize measured labor/time capacity only. Do not claim savings from avoided claim leakage, lower settlements, fraud prevention, or improved recoverability until real historical data supports those claims.

## Post-session output
Within the same day, produce:
1. Product scorecard.
2. Commercial scorecard.
3. Top 3 friction items.
4. Top 3 must-have features.
5. Buyer/champion map.
6. WTP/pricing evidence.
7. Security/procurement blockers.
8. One explicit next step.
9. GO / PIVOT / STOP / INSUFFICIENT_DATA recommendation with rationale.
