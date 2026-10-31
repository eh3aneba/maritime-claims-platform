# Design Partner Pilot Instrumentation

## Purpose
Measure whether MCRI reduces claim-handler effort and improves control without confusing product telemetry with claim evidence.

## Safety scope

This is **measurement instrumentation**, not permission to use real
policyholder documents or to activate local/external AI. As of 31 October 2026
real-data Pilot v1 remains **NO-GO** under
[#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647).
Use only approved **fictional/synthetic** H&M machinery cases for a discovery
rehearsal. The AI provider must remain disabled unless separate
[#752](https://github.com/eh3aneba/maritime-claims-platform/issues/752)
independent acceptance and explicit authorization have been completed.
Do not treat an OCR processing pass as accurate Persian negation, original
source verification or human sign-off ([#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810)).
Do not upload volunteered customer files or infer real-data consent.

A recorded KPI means **observed in the selected permitted workflow**, not
that the system is ready for production. AI acceptance and AI-related time
savings are **Not measured** when AI is disabled. Never substitute an expected
threshold, synthetic-only model test or deterministic baseline for an actual
human-reviewed measurement. Record blocked tests and unsupported features
explicitly.

## Session workflow
1. Open **Pilot** in the application.
2. Select the claim under test.
3. Enter the participant's manual baseline time for producing an equivalent Initial Assessment, if known.
4. Start the pilot session.
5. Run only the authorized synthetic claims workflow, without enabling unaccepted AI or external evidence connectors. Server-side actions are recorded where instrumented.
6. Capture explicit feedback whenever a false positive, false negative, workflow friction point or value signal is observed.
7. End the session and review the scorecard/backlog.

## Metrics currently derived
- Session elapsed time
- Time to first Initial Assessment generation
- Estimated time reduction versus entered manual baseline
- AI review approve/edit/reject counts and rates
- Completed task count and average task age at manual completion
- Document request sent count
- Missing-document precision and recall proxy from explicit validation feedback
- False-positive / false-negative counts
- Average user rating
- Medium+ usability/workflow friction count

## Target scorecard
Current pilot targets are decision thresholds, not contractual performance claims:
- AI approval rate: >= 80% (only if the AI acceptance gate is separately approved and the sample was actually evaluated; otherwise Not measured)
- Estimated Initial Assessment time reduction: >= 30%
- Missing-document precision: >= 90%
- Average participant rating: >= 8/10
- No critical pilot feedback

A target with no supporting measurements is shown as **Not measured**.

## Feedback verdicts
Useful values include:
- `correct`
- `true_positive`
- `false_positive`
- `false_negative`

For missing-document evaluation, a false negative means the participant identified an important required document the rules engine did not surface.

## Backlog generation
Each feedback item is converted into a proposed backlog item:
- Critical severity -> P0
- High severity or false-positive/false-negative validation -> P1
- Medium -> P2
- Low -> P3

A Product Owner still decides whether to accept, merge, defer or reject each proposed item.
