# Commercial Validation & ROI Framework v1.0

## Objective
Turn a design-partner session into falsifiable evidence about value, buyer, budget, pricing, and buying process.

## ROI model — deliberately conservative
The early model only values labor/time capacity:

`minutes_saved_per_claim = manual_baseline - observed_time_to_first_assessment`

`annual_claims_in_scope = annual_relevant_claim_volume × adoption_rate`

`annual_hours_saved = minutes_saved_per_claim / 60 × annual_claims_in_scope`

`annual_labor_value = annual_hours_saved × fully_loaded_hourly_cost`

If an annual willingness-to-pay range exists:

`WTP_midpoint = (WTP_min + WTP_max) / 2`

`estimated_ROI_multiple = annual_labor_value / WTP_midpoint`

`estimated_payback_months = WTP_midpoint / annual_labor_value × 12`

### Important limitations
- These are pilot estimates, not financial forecasts.
- Adoption rate is an explicit assumption and must be recorded.
- Do not value claim leakage, settlement reduction, fraud prevention, or recoveries before real evidence exists.
- If inputs are missing, display `Not measured`; never backfill assumptions silently.

## Commercial evidence hierarchy
### Strong
- paid-pilot amount accepted or counter-offered;
- annual WTP range stated;
- named buyer/champion/budget path;
- procurement or security meeting scheduled;
- next step with owner and deadline.

### Medium
- buying stage identified;
- budget owner identified but no budget yet;
- deployment/security requirements understood;
- clear pricing-model preference.

### Weak
- generic interest;
- feature suggestions;
- positive rating without WTP;
- request for information without a committed next action.

## Internal pricing tests
Use as interview anchors, not public list pricing:
- paid pilot: USD 5k / 10k / 20k;
- annual platform: USD 20k / 40k / 75k.

Record where approval friction changes. The purpose is to find the buying threshold, not to maximize the first quote.

## GO criteria
A session can produce a GO recommendation when:
- measured product signals do not fail core targets;
- buyer identified;
- champion identified;
- WTP signal present;
- concrete next step committed.

Budget approval is valuable but not mandatory for the first GO; it is reported as a separate check.

## PIVOT criteria
Typical reasons:
- measurable time/trust/value targets miss;
- participant is interested but cannot identify buyer/WTP/next step;
- security/deployment requirements invalidate current packaging;
- strong value appears in a narrower workflow than the current product scope.

## STOP interpretation
The software may label a **session** STOP only when explicit no-interest is recorded with no WTP and no next step. Company-level stopping decisions should be based on repeated patterns across appropriate design partners, not one interview.

## Portfolio-level commercial questions for later
After 3–5 pilots, compare:
- which customer segment has highest time reduction;
- where AI acceptance is highest;
- which role becomes champion;
- median WTP range;
- common security blockers;
- sales-cycle expectations;
- which feature consistently drives commitment.
