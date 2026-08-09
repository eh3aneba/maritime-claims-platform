# Sprint 6C — First Design Partner Cohort & Outreach System

## Status
COMPLETE — outreach operating system implemented; real market cohort not yet populated or contacted.

## Objective
Operationalize the path from qualified prospect to paid pilot with explicit qualification, contacts, outreach touches, stage progression, and versioned paid-pilot offers.

## Beachhead
The first cohort prioritizes medium marine insurers/H&M claims teams and ship managers because the current MVP is optimized for machinery/H&M claims. Average adjusters/claims specialists are useful expert design partners; P&I correspondents are secondary until P&I-specific workflows are added.

## Cohort target
- 8–12 initially qualified prospects
- 5 discovery conversations
- 3 controlled design-partner pilots
- at least 1 paid pilot

These are operating targets, not forecast conversion rates.

## Qualification score
100-point deterministic founder-priority score:
- Pain intensity 25
- Machinery claim volume 20
- Buyer access 20
- Data availability 15
- Security fit 10
- Pilot willingness 10

A ≥75, B 60–74, C 40–59, D <40. Score ranks founder attention; it does not predict purchase probability.

## Persisted entities
- design_partner_accounts
- design_partner_contacts
- outreach_touches
- paid_pilot_offers

## Funnel stages
Prospect → Contacted → Discovery → Demo → Pilot Qualified → Pilot Proposed → Pilot Active → Paid Pilot → Customer / No Fit.

Stage progression is evidence-based and should not advance on vanity signals such as email opens or generic praise.

## Paid pilot v1
Suggested controlled offer: 30 days, 5–10 H&M machinery claims, one claims team, approved anonymized/synthetic data, measurable success criteria, no automated coverage/liability/root-cause/settlement decisions.

Internal price-test anchors remain USD 5k/10k/20k for the controlled pilot and USD 20k/40k/75k annual platform discussion. These are validation anchors, not published prices.

## Safety / scope
The outreach module is GTM data only and does not alter claim evidence, coverage, reserve, assessment, or settlement records.

## Validation state
No real design partner has been contacted or commercially qualified by this implementation alone. The next step is to populate 8–12 real candidate accounts from the founder's network and public market research, then run founder-led discovery using the playbook.
