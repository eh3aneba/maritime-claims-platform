# ADR-027 — Pilot instrumentation is server-grounded and feedback-aware

## Status
Accepted — Sprint 6 Phase A

## Decision
Design-partner measurement uses two complementary evidence streams:

1. **Server-grounded telemetry** for consequential workflow actions such as AI review outcomes, document-request actions, task completion and Initial Assessment generation/approval.
2. **Explicit pilot feedback** for judgments the software cannot infer reliably, including usability friction, false positives, false negatives, perceived value and missing-document accuracy.

Pilot events are append-only and tenant/claim/session scoped. Feedback is also append-only. Scorecards are derived views, not authoritative claim records.

## Rationale
Browser click telemetry alone can overstate usage and is easy to misinterpret. Server events prove that a real claim action completed. Conversely, the server cannot know whether a correct-looking rule was genuinely useful or a false positive, so human validation remains necessary.

## Safety boundaries
- Pilot metrics never change coverage, causation, reserve, cost recoverability or settlement decisions.
- Missing-document precision/recall is calculated only from explicitly labeled pilot feedback.
- A target with insufficient evidence remains `Not measured`; missing data is never converted into a synthetic pass.
- Backlog priority is a triage suggestion, not an automatic engineering commitment.
