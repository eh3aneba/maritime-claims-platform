# Phase 12J — Portfolio Claims Triage & Handler Workbench

## Product outcome
Give a claims handler or manager one governed portfolio screen that shows which visible claims need operational attention, why each claim is ranked, and where to continue the existing controlled workflow.

## Foundation scope
- tenant-scoped portfolio metrics;
- deterministic priority tiers: routine, elevated, urgent, critical;
- factor lineage from current controlled source state;
- candidate time-bar and ClaimTask date semantics kept separate;
- handler assignment scoping for claims-handler users;
- filters for priority, claim status/type, attention category, source workflow, handler and due-soon state;
- source workflow deep links;
- deterministic rank hash (`12J.1`);
- browser journey covering a multi-claim ranked queue and lineage drill-down.

## User interpretation
The Claims Workbench prioritizes **human workflow attention**. A higher score means the existing controlled signals justify earlier human review. It does not mean a claim is covered, liable, recoverable, more severe in ultimate-loss terms, or worth a particular reserve/settlement value.

## Current factor families
- handling severity from Severity & Reserve Support;
- candidate time-bar urgency from Recovery & Time-bar;
- open Financial Review flags;
- missing evidence and conflict signals from current Claims Intelligence;
- open ClaimTasks and their existing due dates;
- pending different-human AI Decision Log review;
- content-free governed Claim Q&A operational failure/fallback state.

## Explicit exclusions
No autonomous assignment, no legal-deadline determination, no coverage/liability/causation/recoverability scoring, no reserve mutation, no settlement/payment recommendation, no correspondence generation, no ClaimFact mutation, no raw evidence/model content in portfolio rows.

## Acceptance gates
- backend tenant isolation and latest-snapshot tests;
- deterministic rank hash test;
- candidate-date semantics test;
- frontend typecheck/build;
- full design-partner browser gate including Claims Workbench;
- exact-head Continuous Integration green;
- exact-head Supply Chain Security green;
- fresh explicit user authorization before merge.
