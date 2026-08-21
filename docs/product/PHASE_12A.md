# Phase 12A — Source-linked Claims Intelligence Engine

## Objective

Give an H&M machinery claims handler one defensible, source-linked view of what happened, what evidence is missing, what conflicts, what requires marine/policy/financial review, what rights may need preservation and what to do next.

## MVP

Initial scope is main-engine and turbocharger machinery claims using the platform's current evidence controls.

The Intelligence workspace contains:

1. Executive claim snapshot
2. Chronology
3. Machinery context
4. Evidence available and missing evidence
5. Conflicts
6. Technical hypotheses
7. Policy / marine issue flags
8. Financial / adjustment leads
9. Recovery leads
10. Deadline / time-bar leads
11. Ranked next actions
12. Source lineage and human review controls

## Handler workflow

- Build or refresh a content-addressed intelligence snapshot.
- Inspect why each item was surfaced and the exact structured source references.
- Accept, edit or dismiss the candidate.
- Optionally convert a reviewed recommended action into a controlled claim task.
- Keep the intelligence snapshot immutable; store human decisions separately.

## Marine issue spotting included in 12A

- H&M machinery missing-document requirements;
- overdue maintenance / recent-overhaul / deferred-maintenance / temporary-repair investigation hypotheses;
- unresolved chronology conflicts;
- policy period, deductible, limits, exclusions, warranties, notice and time-limit review flags;
- financial control flags;
- candidate AAA D1 / D2 / D6 cost-review prompts;
- PA / Sue & Labour / salvage / General Average classification review prompts when emergency-expense indicators exist;
- potential third-party or workmanship recovery preservation leads.

These are prompts for qualified human review, not conclusions that any rule, clause, exclusion or recovery theory applies.

## Guardrails

- source-linked by default;
- tenant scoped;
- immutable snapshot and item hashes;
- append-only human decision chain;
- no new external provider scope;
- no autonomous coverage, liability, causation, recoverability, reserve, settlement, payment, fraud or recovery decisions;
- no silent updates to approved claim facts or assessments.

## Evaluation targets

Real design-partner H&M machinery cases should later measure:

- time to first defensible assessment;
- chronology preparation time;
- missing-document precision and recall;
- contradiction-detection precision;
- handler effort saved;
- intelligence accept/edit/dismiss rates;
- unsupported-output rate and source-grounding validity if provider-assisted synthesis is later enabled through the governed AI plane.

## Exit criteria

A handler can open a machinery claim, build a versioned intelligence view, inspect source lineage for each material item, and take a controlled human action without any candidate becoming an authoritative claim fact or claim decision automatically.

## Next phase

Phase 12B expands the versioned, explainable Marine Rules Engine so the intelligence layer can cite richer marine-insurance and adjustment logic instead of relying on limited first-pass issue-spotting prompts.
