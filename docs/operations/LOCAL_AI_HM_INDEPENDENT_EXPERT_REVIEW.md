# #752 — independent H&M review preparation for fixed synthetic cases

This is a **blank, non-approving** checklist for three code-owned
synthetic machinery-loss cases. It is not a human-coded ground truth,
not an assessment of coverage/liability and not a real claim.

From the SeeClaims repository root, using PowerShell or a shell:

```powershell
python -m scripts.pilot_local_ai_hm_expert_review_checklist --print-unfilled-synthetic-hm-expert-checklist
```

The tool prints only three fixed scenario names, source IDs, bounded
criteria identifiers, and explicit pending / FALSE approval fields.
It accepts no customer data, free text, evidence paths, reviewer identity,
model output or external URLs. It does not contact Ollama, save annotations
or submit an adjudication.

## Independent specialist workflow — outside the tool

1. Appoint an independent H&M machinery claims specialist, document their
   competence and any conflicts of interest in an approved private system.
2. Give that specialist the **invented source records** separately from
   model candidate outputs. Use a **blind** reference coding phase before
   the specialist sees model-generated quotations, success counters or
   deterministic code-authored baseline.
3. For each scenario, separately assess exact source attribution, omissions,
   unsupported assumptions and the case-specific ambiguity:
   - `complete_records`: supplied maintenance/log extracts are not
     independently verified; keep reported alarm and shutdown distinct.
   - `missing_engine_records`: **not supplied** is not proof of
     **nonexistence**; document existence remains unknown.
   - `conflicting_alarm_times`: retain both separately attributed
     accounts and mark their conflict unresolved, rather than selecting
     one time as fact.
4. Record source-version references, blinded reference decisions,
   disagreements and adjudication rationale in an approved
   access-controlled human-review system. Do not put reviewer identity,
   raw claims, customer records or sensitive comments in GitHub CI logs
   or the example CLI output.
5. Only then compare coded human references with model observations.
   Record misses and false assertions, not just supported quotations.
   A separate privacy/security owner and an H&M claims owner must sign
   off any proposal to expand beyond synthetic fixtures.

The program is deliberately incapable of marking a review as complete.
A human must actually perform the work, and the resulting approved
private review record must be assessed separately. The phrase-matching
reference used in existing smoke tests is **not** expert ground truth.
Three invented cases and nine model calls are not a performance study.

Tests (no network/model access):

```bash
python -m unittest scripts.tests.test_pilot_local_ai_hm_expert_review_checklist -v
```

**Pilot GO=NO.** Independent H&M labels, runtime/model provenance,
host network isolation, data permissions and operator sign-off are
still missing until separately verified.
