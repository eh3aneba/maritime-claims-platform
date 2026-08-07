# Design Partner Test Script

Use this script during a 45–60 minute product walkthrough. Record friction and incorrect outputs; do not coach the user through ordinary navigation unless they are blocked.

## Scenario

You are the Claims Manager reviewing the synthetic MT ORION main-engine turbocharger claim.

## Tasks

1. Sign in and locate MT ORION without being told its internal claim UUID.
2. From Claim Overview, explain the current status, reserve and incident summary.
3. Open Requirements & Workflow. Identify the outstanding critical evidence and explain why `Requested` is not the same as `Received`.
4. Open AI Review. Find at least one group that needs judgment and inspect its source context.
5. Open Chronology. Identify the shutdown-time discrepancy and explain what the system does **not** decide.
6. Open Technical Review. Identify evidence supporting the maintenance investigation flag and at least one unknown/follow-up item.
7. Open Financial Review. Explain why the USD 260k and USD 470k quotations are not added together as claim exposure.
8. Open Initial Assessment. Identify why it is Preliminary rather than Final and inspect at least one Source Manifest.
9. Return to the claim and identify the next action you would take if this were a real claim.

## Observer questions

After the walkthrough ask:

- Which screen would you use most often?
- Which warning or label was unclear?
- Did any screen feel too dense or too empty?
- Which AI review action felt repetitive?
- Would you trust the chronology enough to use it as a working investigation timeline? Why or why not?
- What information would you still keep in Excel/email outside this platform?
- What would prevent you from using this on a live claim tomorrow?

## Pilot exit criteria

A design-partner session is considered usable when the participant can complete the nine tasks without developer intervention, no P0 data-integrity issue appears, and all observed P1/P2 friction is logged for prioritization.
