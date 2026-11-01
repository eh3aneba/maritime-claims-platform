# #867 risk-first verification and bounded remediation plan

Observed 2026-11-01, Asia/Tehran. This is a documentation/security review,
not a second implementation package or pilot authorization. Production code,
workflows, branch rules, credentials and external integrations are unchanged.

## Exact candidate and admission status

- Main: `fa2c471463f5aecb988f89e791aae359385227e4`.
- [#867](https://github.com/eh3aneba/maritime-claims-platform/pull/867): Draft,
  head `78f6b3de1ba2965de929850c383c8ed7665dcae8`; PR merge ref
  `283ab372d7b5a80c212f6d2494f769604b93b0bd`.
- [#866](https://github.com/eh3aneba/maritime-claims-platform/pull/866): unchanged
  Draft, head `998858f31d8c6ff8b8a2fe4b1184d787975efdf3`. No merge, review-state
  change or new optimization is part of this work.
- GitHub public PR/check/run pages are readable. The running cloud network still
  excludes `api.github.com`; its pending draft entry is not applied to revision 1.
  An authorized `gh workflow run backend-premerge.yml --ref
  fix/auth-bootstrap-model-registry` attempt failed with `Forbidden` before a run
  was created. No token is requested or copied into documentation.
- The existing draft policy skipped Full Backend. This is **not** full regression
  success. An API-capable operator must dispatch the existing workflow without
  changing Draft state; all 64 shards and their real pytest execution remain
  mandatory. Manual dispatch validates its event commit; label it separately from
  any later PR merge-ref validation. Preserve all eleven existing required checks.

Hosted run observations are recorded in
[the run inventory](evidence/pr867/hosted-checks.json). Pending runs are not
passes, and old-SHA checks cannot admit a changed candidate. No hosted acceleration
is established; #553's reference remains 44m13s median Backend wall time and about
505.5 shard runner-minutes. #866 needs its own complete measurements including
producer, artifacts, queueing, installs and test execution.

Final observed #867 workflow results at the supplied head:

| Workflow | Run | Result | Reported duration |
| --- | --- | --- | --- |
| Production Deployment Policy | 41325835629 | Success | 14s |
| Supply Chain Security | 41325835638 | Success | 13m49s |
| Continuous Integration | 41325835632 | Success | 15m41s |
| Operational Performance Smoke | 41325835654 | Success | 15m30s |
| PostgreSQL Concurrency Regression Suite | 41325835715 | Success | 16m14s |
| Full Backend Pre-Merge | 41325836131 | **Skipped** | 1s |

All workflow results above were inspected, and no failing hosted workflow was
observed. This is **five successful workflows and one skipped workflow**, not
all eleven required checks green. Full Backend's skip is a validation gap, not
a successful 64-shard run. No rerun, ignore flag, timeout increase, production
fix or green status was introduced to hide it.

## Standalone PostgreSQL verification

[Observed results](evidence/pr867/bootstrap-postgres.json) apply to the exact #867
head with a clean checkout. A fresh, uniquely named disposable PostgreSQL 18.4
database received real Alembic migrations. Each bootstrap used a new Python CLI
process; pytest/application imports could not mask registry initialization.
Only invented identities and generated ephemeral passwords were used.

Seven checks passed: first administrator creation; case-insensitive replay with
unchanged identity/hash despite a different supplied password; disabled/non-admin
user preservation; same-email tenant separation; inactive organization status
preservation; rollback of both organization and user on an actual deferred COMMIT
failure; and unchanged pre-existing tenants after that failure. The failure used
a constraint trigger only in the disposable database, not a mocked successful
transaction. Failure returned nonzero and emitted no bootstrap-complete message.
The temporary database was removed. No production migration or policy changed.

The initial verification harness used the wrong organization field name; that
setup error was corrected to the repository's `Organization.status` enum and is
not included in passing evidence. No additional bootstrap code defect was
reproduced, so this review does not change #867's implementation or SHA.

## Interrupted invocation: investigation and disposition

[Diagnostic summary](evidence/pr867/interrupted-test.json): the same login test
stalled in the restricted executor and was stopped by an **external diagnostic**
25-second budget; its eight-second stack showed TestClient awaiting an AnyIO
portal future while the event-loop thread waited in a selector. This was not a
passing test, nor a changed production/CI timeout.

A local socketpair send in that context returned `EPERM`. A minimal AnyIO
portal callback, importing neither SeeClaims nor PostgreSQL, also stalled and
was stopped after 12 seconds. In the supported execution context, socketpair
and portal controls passed, and the identical login test passed in 9.21 seconds
under the same 25-second diagnostic bound. CPython's selector loop wakes the
other thread by sending to its self-pipe socket; it catches send errors. Denied
IPC therefore explains the reproduced missing wakeup without a database lock.

Current observations show about 32 GiB available memory and no cgroup OOM event;
they do not retroactively prove the original run's resource state. The original
aborted invocation has no captured stack, so retain that evidentiary limit.
There is no demonstrated application deadlock or basis to modify transactions,
assertions, AnyIO internals, retries or timeouts. Use the platform's supported,
scoped execution context for these local ASGI tests; do not disable network
policy, grant blanket access, or mark interrupted runs green.

## Risk-remediation work packages

| Priority / risk | Current evidence and containment | Next bounded work and acceptance | Accountable human dependency |
| --- | --- | --- | --- |
| P0: ClamAV freshness | Real PING, clean DOCX processing and harmless EICAR detection passed locally. Definition update reachability/freshness was not verified. Current preflight probes connectivity, not accepted signature age; a clean verdict is not current-malware-coverage proof | First collect content-free engine/definition version, definition build time, trusted observation time, updater outcome and update reachability on an isolated host. Define an approved maximum-age/future-clock/unknown-state policy before changing admission semantics. Then implement a separately reviewed health/admission boundary, with fixed-time regressions for current, stale, absent, future-dated and unverifiable definitions. An update failure must not be hidden by a PING success; owner-approved last-known-good rules must be explicit. Prove signed-definition and TLS verification, fail-closed unavailable scanning, and received operator alerts | Security/operations owner selects freshness policy, update destinations and isolated host. `database.clamav.net` is an update dependency to review, not permission to bypass the network proxy or disable verification |
| P0: Persian OCR negation (#810) | The original HM-05 critical negation omission remains unaccepted. DOCX browser success and downstream warnings do not repair raster OCR. External inference remains off | Run the existing fixed-original raster probe with pinned local OCR/tool/language-data versions. Retain original raster and extraction hashes and complete observed output privately as appropriate. Compare critical source spans, negation scope, technical terms, pages and locators with independently coded bilingual reference. Keep designated holdout material out of development. A candidate must recover actual original content and pass independent unseen evidence, or the owner must explicitly de-scope critical Persian extraction; never insert an expected negative token or infer a missing phrase to pass | Independent bilingual H&M reviewer and source custodian establish reference, blindness and semantic acceptance. No self-awarded model score or automatic issue closure |
| P0: Source-linked evidence (#850) | Current code binds versions/hashes, preserves stale-source warnings, rejects unverified OCR promotion and records independent workpaper linkage. Hash equality is not proof that a quote faithfully represents the original scan or that a workpaper's content was professionally reviewed | Exercise actual upload/replacement/reprocessing/quarantine and a later discrepancy after fact approval. Verify exact tenant, claim, document family/version, bytes hash, extraction hash, page/locator and current-source state on every review/export path. Historical assessments/exports remain immutable; holds persist and stale approval cannot be reused. Test wrong-tenant, changed bytes/text, concurrent source updates, stale review and idempotent retries. Separate any reproducible bypass into a minimal regression-first PR. Never auto-clear disputes or overwrite approved history | Authorized adjudicator must review original scans/workpaper contents and explicitly authorize any future resolution lifecycle, with independent role separation and an append-only source-bound receipt |
| P1: Independent H&M acceptance (#647/#752) | One automated HM-01 native rehearsal processed four invented documents and produced a source-bound preliminary XLSX aid. Human task time, usefulness, commercial fit and expert quality were not assessed. No local/external model was evaluated | Use the existing synthetic multi-document workflow rather than another demo tool. Pre-register what a handler must find, what stays unknown and how source completeness/unsupported assertions are counted. Measure authentication/intake, review, missing/conflicting evidence, chronology, technical/financial review, Assessment and correspondence/export; distinguish machine wait, human review and rework. Compare manual/rules and only an explicitly executable authorized local model on equivalent scenarios. Preserve failures and abstentions. Record corrections and a real reviewer decision per workflow stage | Named H&M handler/reviewer, product owner and source/reference custodian; customer permission and commercial acceptance remain separate. Software tests cannot sign for them |

Relevant existing regressions include `test_ai_approved_fact_source_revalidation.py`,
`test_ocr_discrepancy_review_admission_hold.py`,
`test_ocr_ai_review_original_source_guard.py`,
`test_ocr_discrepancy_independent_review.py`, `test_ocr_review_workpaper_binding.py`
and `test_claim_pack_stale_ai_fact_source_warning.py`. This inventory is not a
claim that these suites were executed by this review. The prior #867 local
16-test result remains distinct from the new seven PostgreSQL scenario checks.

For #835, retain the existing fail-closed PDF response and complete Unicode XLSX
fallback until a separately scoped licensed-font/shaping/layout implementation
passes extraction, visual bidi/negation, multipage overflow and independent
bilingual review. Do not replace unsupported source characters with `?` or
silently represent an incomplete PDF as faithful evidence.

## Ordered next actions and approval boundary

1. Apply the pending API network setting, dispatch #867's existing full Backend
   workflow, and obtain final results for every applicable exact-commit hosted
   check. Diagnose actual failures; do not change Draft policy or branch rules.
2. Complete isolated signature-freshness observations and owner-approved policy;
   implement only an independently demonstrated defect or an approved bounded
   control in its own PR. Preserve #866 unchanged until measured admission.
3. Execute source-version/discrepancy scenarios and obtain real bilingual H&M
   review of synthetic originals. Keep #810/#835/#850, #653 matched DB+Evidence
   restore/rollback/alerts, and #764 private historical security triage open until
   their own evidence exists.

No merge, deployment, real customer files, external AI/evidence activation,
automated insurance decision, security exception, expert signature or pilot GO
is authorized by this review. The existing execution roadmap remains the
authoritative project index; this document is a focused risk/verification annex.
