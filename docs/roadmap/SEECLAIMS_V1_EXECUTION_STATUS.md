# SeeClaims — Execution Roadmap v1 | Status and gates

## Active SQL-template canary — security first (2026-11-04, Asia/Tehran)

Principal branch `test/credential-lineage-final-freshness`, Draft PR #875;
this containing commit anchors the candidate. Main remains
`811461563fa2076f751ac828c9821b4a27353f25`. The unsafe single-validation
shortcut below remains rejected. This separate approach reuses only two
immutable SQL statement structures for profile reads, binding typed tenant
and profile UUIDs per call. No rows, Sessions or validation outcomes are cached.
All receipt, approval, final credential-lineage checks and requested row locks
remain. All 25 other profile-service functions are AST-identical to baseline;
Session visibility/isolation semantics are unchanged, not strengthened.

Actual isolated local validation: **29 passed**, four existing deprecation
warnings, 58.99s, across profile governance/integrity, credential references,
connection authorization/bootstrap and five new query regressions. Four new
regressions passed against baseline together; the fifth fresh-process case also
passed baseline separately. The first SQL-template prototype failed that fifth
case: early imports captured an unresolved foreign-key bind type. Explicit
`Uuid(as_uuid=True)` bindings fix the confirmed proposal-only defect; the exact
new regression failed before and passed after that fix. Current main was not
shown vulnerable. The original mid-read credential drift guard also passes.

Final-source warm-cache SQLite component: five alternating-order pairs, 1,000
fully validated reads per arm. Median 0.431506s baseline / 0.364106s candidate
(**15.62% lower**); all ten arms executed exactly 2,000 SELECTs. Unchanged slow
synthetic lifecycle test: baseline **511.58s pytest / 518.981s outer**, final
candidate **485.88s pytest / 493.760s outer**, both passed; approximately 5% lower
in this single local comparison. Source SHA256 stayed
`5bd9b4cec06ccf8703300b96d21cacbb362429c0bbf77ea2c7153a2b95d2a247`.
Final service SHA256:
`d16274335d9d8ddb1d4359c1283cb2c9edea83d5f92b592a6896cba3927340c5`.
An earlier warm-import prototype replay was 473.85s; do not substitute it for
the final candidate or pool these stages as identical paired cohorts.

**Review canary only, not accepted or merge-ready.** Local SQLite/Python3.13.16
is not hosted PostgreSQL/Python3.13.17 evidence. One slow baseline/final replay
cannot establish a CI median, tail latency, runner-minute saving or causality;
new subprocess-regression startup cost must be included in whole-CI comparisons.
PostgreSQL row-lock SQL compilation is tested, not independent concurrency proof.
Early restricted-executor TestClient attempts stalled and were terminated without
results; an independent tiny FastAPI reproduction also stalled there and passed
with approved executor permissions. Accepted runs used those permissions.

Previous #875 head `12b76f57d880bf58de7b54d683e5bde7a5cb40bb` passed its
previously executed hosted workflows; Draft-triggered Backend was skipped, not
passed. Authorized full64 manual run **41769488626** is pinned to that old head;
latest observation before preparing this commit: **62/64 shards passed, no
failures, two running**. It cannot validate this new production-source candidate.
Do not cancel it to hide a result. Read live #647/#553 and PR #875 for subsequent
exact-head outcomes. New candidate requires its own all64 and 11 required gates;
Draft policy, workflow names and classifier remain unchanged. No merge/deployment.

Next three: finish/evaluate old full64 then obtain final-head full64 and all
required gates; perform a bounded comparable confirmation including PostgreSQL,
cache/runtime differences and the added test cost; review acceptance or rejection
before adoption. Rollback is an ordinary revert of SQL construction, without a
schema/data migration. #866 remains isolated unchanged Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3` and is not adopted.
Security/operations owner and independent bilingual H&M reviewer remain
UNASSIGNED — HUMAN APPOINTMENT REQUIRED; freshness policy NOT APPROVED;
OCR/source-review holds intact, synthetic data only, AI/external adapters OFF.
Customer Pilot remains **NO-GO**. Older entries below are dated history.

## Current safety gate — final credential lineage (2026-11-03, Asia/Tehran)

Main baseline `811461563fa2076f751ac828c9821b4a27353f25` remains unchanged in
production behavior. The shared-manifest and matrix-order experiments were not
adopted; #866 stays unchanged Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3`. See #553 comments 6607851504 and
6611365677 for completed reliability/performance decisions.

One unchanged synthetic replay test passed under local content-free profiling:
557.18s, with prerequisite construction 344.00s and two asserted product actions
205.35s. 1,851,209 SQL executions led to a proposal to reuse a validated profile.
Cursor timing excludes fetching/ORM; no speedup was established by that profile.
Reproducible baseline: #553 comment 6613418698 (proposal subsequently withdrawn).

**The initial optimization is rejected on a concrete safety counterexample.**
A new synthetic regression changes an upstream bootstrap receipt while binding
receipts are being checked. Original code rejects the drift; the proposed
single-validation shortcut returns successfully and fails the regression.
The prototype was discarded and production source restored byte-for-byte.
This is a regression in the proposed optimization, not a demonstrated defect
or exploit in the current production implementation. Final upstream checking
must remain effective; no cross-call validation cache or weakened check.

Principal branch `test/credential-lineage-final-freshness` retains only the new
protective test and this status update; this containing commit anchors its head.
Local existing-plus-new credential suite: **4 passed**, 3 existing deprecation
warnings, 15.01s pytest time. The exact final regression also rejected the
prototype (expected failing experiment). Synthetic SQLite/session-local drift
is not proof of real concurrent PostgreSQL behavior. Hosted exact-head checks
remain pending; no optimized candidate, full-regression pass, speedup, merge,
deployment or human signoff is claimed. Test rollback confirms valid reads
recover and the injected drift does not persist.

Next three: review hosted validation of the protective test; investigate an
optimization that preserves final freshness semantics; profile a new candidate
only after security regressions pass. Keep all64 shards,11 required contexts
and the existing classifier. No production configuration or customer evidence.
Security/operations and independent bilingual reviewer remain UNASSIGNED —
HUMAN APPOINTMENT REQUIRED; freshness policy NOT APPROVED; OCR holds intact.
Customer Pilot remains **NO-GO**. The old pending-state entries below are dated
history, reconciled by this entry and the live #647 execution handoff.

## Active source/export reliability — XLSX error-like literals (2026-11-02 UTC)

Current baseline main `26d5e9d0feaa299392dd15505be3d00588bb60b8` normally merged
#873 after all 64 Backend shards and eleven required checks passed. Its post-merge
policy passed; security run 41433546759 is pending its container-image build/scan
(secret history and dependency audit passed). Do not infer the final result.

Principal branch `fix/claim-pack-xlsx-error-literals`; this containing commit
anchors the exact candidate. Reproduced a bounded export defect: openpyxl infers
Excel error cells for source strings such as `#N/A`. All 14 new base/governed
renderer cases failed before the fix. Extend the existing text-literal guard to
error-like strings as well as formula-like strings, preserving exact text without
adding apostrophes or changing snapshots. No dependency, API, policy, migration,
insurance behavior, source provenance or CI-control change. Rollback is a normal
PR revert; never rewrite stored evidence or human decisions.

Actual final local validation: **46 passed**, two existing deprecation warnings,
including all seven recognized error tokens in both renderers, snapshot
immutability, formula protection, authenticated vessel creation/claim export/
download, PDF layout/Unicode fail-closed behavior and governed reporting. An
initial new authenticated-test setup incorrectly passed a string to a UUID ORM
lookup; corrected the test to create/link the synthetic vessel through normal
APIs, then reran the entire targeted suite. Hosted candidate validation remains
pending. No semantic, independent human or operational acceptance is claimed.

Security/operations owner and independent bilingual H&M reviewer remain
**UNASSIGNED — HUMAN APPOINTMENT REQUIRED**; freshness policy **NOT APPROVED**.
No threshold, exception, admission change, OCR hold clearance or real-customer
authorization. Customer Pilot **NO-GO**. These decisions do not block unrelated
synthetic engineering. #866 remains isolated unchanged Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3`; current enforced runtime still excludes
the Actions artifact host, so no known-denied download was retried.

Next three priorities: (1) finish exact-main security evaluation and investigate
real failures; (2) complete exact-candidate full Backend/required hosted gates for
the XLSX fix, preserving Draft policy and all regression coverage; (3) after the
environment owner applies artifact access, verify artifacts and resume #866's
controlled benchmark acceptance without modifying its isolated branch.

## Active independent engineering — PDF page bounds (2026-11-02)

Owner clarification, authoritative until an explicit appointment/approval:

- Accountable security/operations owner: **UNASSIGNED — HUMAN APPOINTMENT REQUIRED**.
- Independent Persian/English H&M reviewer: **UNASSIGNED — HUMAN APPOINTMENT REQUIRED**.
- ClamAV freshness policy: **NOT APPROVED**. No maximum age, exception or production
  admission decision is authorized. The Product Owner will appoint accountable
  humans before production/real-customer pilot approval; private references may
  identify the independent reviewer. Do not self-sign or clear OCR holds.
- Continue independent engineering/synthetic/read-only work. Escalate only a task
  that actually needs those human decisions. Customer Pilot remains **NO-GO**.

Main baseline `6fbe446f0ad9a1dd15b901555ece4fd50d3b74a8` includes normally merged
#872 with all 64 Backend shards, all eleven contexts and post-merge policy/security
passed. Branch `fix/claim-pack-pdf-page-width` is the single active implementation;
this containing commit anchors its exact head. #866 stays unchanged Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3`. Artifact access is still not enforced;
its saved draft does not block this unrelated development. Owner clarification
is also recorded on #653 comment 6573943690 and #810 comment 6573944013.

Reproduced #835 layout defect: character-count wrapping can place wide source
text beyond the 612pt page and hide following negation. Original Poppler output
clipped a 75-W synthetic identifier and omitted following words; two actual
renderer geometry regressions failed before correction. Wrap against bundled
Helvetica advance metrics for the existing 9pt font/54pt margins, paginate after
wrapping, and fail closed with the existing XLSX alternative when a glyph cannot
be measured. Keep source snapshots and previous exports immutable. The metrics
come from the already locked pypdf dependency; no new font, dependency, model,
source correction, insurance rule, signature threshold or production config.

Actually passed: **29 targeted tests**, including base/appendix geometry, wide,
narrow and currency glyphs, long multi-page content, snapshot immutability,
authenticated export/download, unsupported-Persian/XLSX and stale-source warnings.
Independent Poppler checks found all words within existing horizontal margins,
including the previously invisible negation in the direct writer. Existing
Starlette/httpx and HTTP-422 deprecation warnings remain. This is engineering
validation, not bilingual/expert or customer acceptance. Exact-head hosted checks
and full 64-shard Backend are pending; no success is inferred from local tests.

Next three executable priorities: (1) complete protected exact-head validation,
fix actual failures and merge normally only if all checks permit; (2) continue
bounded source/export reliability work while #810/#835/#850 acceptance stays
open; (3) resume #866 artifact-dependent acceptance only after access is actually
applied. Freshness/admission implementation and independent signoff alone wait
for human appointments/policy. Rollback is a normal PR revert, never a rewrite
of stored source, human decisions or historical evidence. No deployment.

## Active PDF fidelity correction — 2026-11-02 (Asia/Tehran)

Main baseline `cc461db7cd2adb9e66974ce3ece371916badd11f` passed post-merge policy
and security. #865/#867/#869/#870/#871 are merged; live completion receipt:
issue #647 comment 6571866515. Older pending-state notes below are historical.

Principal branch `fix/claim-pack-pdf-winansi-encoding`; production patch commit
`60041efd909e7f90db6a76fa470b930a43911888`, with this containing commit anchoring
the updated head. Both PDF writers encoded CP1252 but omitted WinAnsi font
encoding. Euro/em-dash/curly quotes extracted as control characters. Declaring
the matching font encoding fixes that independently reproduced export defect.

Two new renderer regressions failed before the fix. All **18 targeted tests**
passed afterward, including authenticated export, immutable snapshot, unsupported
Persian PDF rejection/XLSX fallback, recovery/correspondence and stale-source
warning appendices. Existing Starlette/httpx/HTTP-422 deprecation warnings remain.
Independent Poppler extraction preserved exact synthetic currency/quote/escape
text in both writers; a main-page raster was inspected as an engineering check,
not bilingual or expert acceptance. Hosted exact-head checks and full 64-shard
Backend remain pending. No dependency, font, migration, insurance rule, freshness
policy, CI classifier or existing required check was changed.

Rollback: revert this PR normally; never rewrite historical snapshots/exports.
#835 stays open for broader Unicode/RTL fidelity and human acceptance. No Persian
rendering support or OCR-quality repair is claimed. The artifact-access draft is
saved but not published/applied; no denied download was retried. #866 remains
unchanged Draft at `998858f31d8c6ff8b8a2fe4b1184d787975efdf3`.

Next three priorities: (1) obtain complete exact-head required results including
all 64 Backend shards, fix actual failures, then consider protected merge;
(2) obtain authorized source review and security-owner freshness policy without
clearing holds; (3) environment owner reviews/publishes artifact access, then
engineering verifies access and resumes #866 acceptance. Customer Pilot **NO-GO**.

## Current protected-review handoff — 2026-11-02 (Asia/Tehran)

Current main baseline: `d9ee0941337b54d685de22358ea0de4b9b2f39fc`.
#865 merged normally at 10:30 Asia/Tehran from exact candidate
`db899c0ef0569f8646bff74154ec87c99d9aa0d2` after all 11 latest required contexts
and fresh-runner operational recovery passed. Its AGENTS.md/setup guide are now
present; local documentation links/references and whitespace passed. #871 merged
as `fdad762df6bb0374011e40ab5ccf956bb105fa9c` after exact-head browser, operational
recovery and all required checks. Its post-merge security 41401527734 passed.
No administrator bypass, production deployment or insurance approval occurred.

Active review branch: `docs/hm05-native-source-rehearsal`, existing #870. Previous
published head `f201644fc448bdc7d7287aaf2982808ed950ec9b`; this containing commit
anchors the updated head. Main was integrated without conflicts. The guard fix,
analyzer and immutable packet are unchanged by integrating #865. Prior-head
hosted safety run **41402385072 passed**: eight packet checksums, six guard tests
(34 normal/-O subprocess scenarios), eleven analyzer tests. Fresh exact-head
required results are pending after this update; do not reuse old-head green
checks as current merge acceptance. All local tests described above actually ran.
A subsequent full `python -O` replay on fresh isolated PostgreSQL and actual
ClamAV passed with the pinned historical worker image; its new receipt is
`docs/pilot/hm-multidoc-v1/validation/hm05-optimized-guarded-worker-2026-11-02.json`.
It binds helper commit f201644fc448bdc7d7287aaf2982808ed950ec9b and the unchanged
helper hash. The transcript/hold remained identical, no facts/assessments were
created, non-test/populated-dataset refusals returned 1 without count changes,
and all disposable services/private files were removed. This is not a rebuilt
latest-main image or independent acceptance; original receipts remain immutable.

The helper's original optimization bypass was isolated without app/DB access;
explicit failures replace assertions, import is inert, and runtime, DB/source,
empty-dataset and scanner/worker/hold checks remain fail-closed. No historical
receipt, original source, transcript, reviewer field or source hold was rewritten.
A read-only path-scoped regression workflow covers the safety fix and changes no
existing required context. A bounded secret-pattern review found no token/private
key/signed-URL patterns; this is not a full security certification.

GitHub issues #850, #810 and #653 now record actual merged outcomes and pending
source adjudication, OCR semantic quality, security policy and selected-host
acceptance; none was closed. #866 remains unchanged Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3`, benchmark acceptance incomplete.
The #865 monitor exited after its protected merge. No local frontend/DB/scanner
or previous monitor is intentionally running. GitHub workflows provide actual
hosted validation; any new bounded watcher must be recorded explicitly.

Next three priorities: (1) evaluate new #870 exact-head safety and required gates,
fix actual failures and merge normally only if all protections permit;
(2) evaluate #865-main post-merge policy/security results and support authorized
bilingual review without clearing holds; (3) keep #866 isolated pending repeated
benchmarks, hosted node/outcome equivalence and negative artifact/rerun evidence.
Human decisions remain security-owner freshness/admission policy, independent
H&M adjudication, selected-host operation and customer permission. Customer Pilot
remains **NO-GO**. Valid normal protected merges are authorized.

## Latest verified execution — 2026-11-02 (Asia/Tehran)

Main `fdad762df6bb0374011e40ab5ccf956bb105fa9c` contains normally merged #871.
Its candidate `1f5bae15b91bae8a6d6497c309c18fd0bbdc5866` passed all 11 latest
required contexts, real hosted browser journeys, operational smoke and fresh-runner
recovery. The exact-head monitor merged without bypass and exited normally.
#869 post-merge security 41399598339 passed. #871-main policy 41401527630 passed;
post-merge security 41401527734 is still pending, not claimed as passed.

Existing #865 agent instructions were reviewed and integrated with main at head
`db899c0ef0569f8646bff74154ec87c99d9aa0d2`. Its only changes from main remain
AGENTS.md and the setup guide; relative links, lockfile references, safety/merge
instructions and whitespace checked. No hosted failures observed; operational
smoke remains pending. No application test was unnecessarily re-run for that doc diff.

#870's own unmerged replay helper had an optimization bypass: its original UID
preflight rejected injected UID 0 normally but continued with optimize=2, safely
reproduced without app/DB access. Explicit failures now protect all settings,
DB name, source hash, empty-data and scan/worker/hold readbacks. Import is inert.
Six regression tests passed across **34 ordinary/optimized subprocess scenarios**;
eleven offline CI analyzer tests passed. A narrowly scoped read-only workflow now
runs those tests plus frozen-packet checksums; it changes no existing required
context, runtime configuration or production admission policy. The corrected
Docker helper has **not** been rerun; historical receipts/hashes are unchanged.
No reviewer acceptance or application hold was filled or cleared.

Current evidence branch: `docs/hm05-native-source-rehearsal`, existing #870,
preceding published head `11a80df68a741a6d94bed8f5e7047e72a9618af4`; the containing
commit anchors this update. Latest main is integrated without conflict. #866
remains unchanged Draft at `998858f31d8c6ff8b8a2fe4b1184d787975efdf3` and is not
benchmark-accepted. No duplicate PR or deployment was created.

Next three priorities: (1) evaluate #865's final exact-head gate and merge normally
only if all checks permit; (2) obtain hosted safety regression results for #870,
then review its protected readiness before bringing the persistent record to main;
(3) support authorized bilingual source review and preserve #866 isolation until
benchmark and artifact-equivalence acceptance. Security-owner freshness/admission
policy, independent H&M adjudication, selected-host operations and customer-pilot
permission remain human dependencies. Customer Pilot remains **NO-GO**.

## Current handoff — observer merged; OCR revalidation active (2026-11-02)

**Main:** `cab2f32e517565341d4e5171ea3e7642814a372d`.
[#869](https://github.com/eh3aneba/maritime-claims-platform/pull/869) merged normally
at 09:53 Asia/Tehran after exact candidate
`fd4296f38b909a8770dea3d28d93fda37aeb87a9` passed all 11 latest required checks.
Operational run **41398380637** passed live-stack smoke, synthetic backup/restore,
post-recovery claim read, fresh-runner recovery and final gate. The merge used
squash and expected-head matching, with no administrator bypass. The observer
introduces no freshness threshold, evidence admission change or production claim
behavior. Main policy run 41399598276 passed; security run 41399598339 is pending.
Earlier bootstrap-main security run 41397874183 also finished successfully.

**Principal branch:** `feat/ocr-independent-review-readback`, existing
[#871](https://github.com/eh3aneba/maritime-claims-platform/pull/871), exact head
`1f5bae15b91bae8a6d6497c309c18fd0bbdc5866`, now ready for normal hosted validation.
Both merged main changes were integrated without conflict. Git trees for
`apps/web`, `apps/api` and `tests/browser` match the integrated source used in
local verification. Actually passed: four Node DTO tests, five synthetic SQLite
backend review/workpaper tests, TypeScript, standard production build, workflow
lint and bilingual compiled-frontend browser regression with all API responses
mocked and **zero API writes**. No real reviewer assertion was entered.

Local build setup problems were resolved rather than counted as passes:
cross-worktree dependency symlink rejected by Turbopack; restricted worker port;
then a clean generated cache with supported permissions passed. Lockfiles and
build settings were unchanged. Generated tracked files were restored and the
loopback frontend stopped. One existing Starlette/httpx deprecation warning
occurred in the passing backend suite.

Exact-head hosted #871 Backend **41399705085** passed classifier and gate;
its shard placeholder and changed-test job correctly skipped under the unchanged
source classifier. CI **41399654936** (browser E2E), operational **41399654974**,
and security **41399654881** (container scan) remain pending. Concurrency
41399654846 and policy 41399654942 passed. The earlier Draft-event Backend skip
41399654901 is not execution evidence; the normal ready event completed successfully. Do not
merge based on local tests or old-head results. Preserve all required contexts.

#866 remains unchanged Draft at `998858f31d8c6ff8b8a2fe4b1184d787975efdf3`;
its benchmark acceptance remains incomplete. HM-05 packet's eight checksums
passed again and reviewer fields/holds remain pending, not self-approved.
Evidence branch #870 remains `docs/hm05-native-source-rehearsal`, preceding head
`e1a395afd210cba2c1664ebb9d7ad01705ef5539`; the containing commit anchors this
handoff. No duplicate PR, deployment, production configuration or network-policy
change occurred. No local server/test process is intentionally left running.
GitHub Actions above are the actual supported validation executions.

Next three priorities:
1. Evaluate #871 exact-head hosted outcomes and actual failures; merge normally
   only when all applicable validation and required protections permit.
2. Evaluate observer-main post-merge security result; support authorized bilingual
   H&M review without clearing holds or inventing expert/source acceptance.
3. Retain #866 isolation until repeated benchmarks, hosted node/outcome equivalence
   and artifact failure/rerun criteria are satisfied; known Actions storage access
   still needs an environment-owner policy decision before independent downloads.

Human dependencies: security-owner signature freshness/admission policy,
independent H&M source adjudication, operator-host acceptance and customer-pilot
permission. **Customer Pilot remains NO-GO.** Valid normal merges are authorized.
Historical entries below are retained as dated evidence, not current PR states.

## Active observer validation — 2026-11-02 (Asia/Tehran)

Principal implementation branch: `feat/clamav-signature-observation`, existing
[#869](https://github.com/eh3aneba/maritime-claims-platform/pull/869), exact head
`fd4296f38b909a8770dea3d28d93fda37aeb87a9`. Main
`a2b5b87466355891d4e4d33320aabdee076a22d4` was merged into this feature branch
without conflict; its five-file observer diff remains separate from application
behavior. #869 is now ready for review under the owner's merge authorization.

Actually executed: **16** fixed-clock observer/scan-probe tests, **11** scope/shard
guard tests, workflow actionlint, and whitespace verification all passed. The
first test invocation mistakenly ran from the evidence worktree and could not
import the observer test; the corrected feature-worktree invocation passed.
No customer data, live production scanner or external AI was used.

Exact-head hosted results: observer regressions 41398380653, Continuous
Integration 41398380634, concurrency 41398380540, supply chain 41398380500,
and production policy 41398380639 passed. The initial push/ready event raced
and used Draft metadata; normal ready validation was reissued on the confirmed
head. Backend run **41398458925 passed its classifier and final gate**, with
shards/changed-test verification correctly skipped for script-only source scope.
Operational run **41398380637 remains pending**; no merge is claimed.

GitHub rejected gated auto-merge because repository auto-merge is disabled.
No repository setting was changed, no check overridden and no admin bypass used.
A normal merge still requires re-reading all 11 latest required contexts and the
exact head once operational validation finishes. Existing main's post-merge
supply-chain run 41397874183 was still pending at the last observation; production
policy 41397874222 passed.

Evidence branch remains `docs/hm05-native-source-rehearsal`, #870, preceding
head `8059f5487f12903c717e6077d5bba2678404ab20`; this containing commit anchors
this handoff. #866 remains unchanged Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3`. #871 remains unchanged Draft at
`99a12529e35ec506ac49463336f16a08c1592a04`; its read-only source-binding parser
and history UI were inspected, but no new frontend validation is claimed.

Next three priorities: (1) evaluate #869 operational and post-merge main security
results, then normal exact-head merge only when every required check permits;
(2) integrate updated main and revalidate #871 without clearing source holds;
(3) retain #866 isolation until benchmark and hosted artifact-equivalence criteria
are satisfied. Security-owner freshness policy, independent bilingual H&M source
adjudication, operational acceptance and customer-pilot authorization remain human
dependencies. No freshness threshold/admission change was made. Pilot is **NO-GO**.

## Verified bootstrap merge — 2026-11-02, 09:36 Asia/Tehran

- Owner-authorized normal squash merge completed for [#867](https://github.com/eh3aneba/maritime-claims-platform/pull/867).
  Verified candidate head: `78f6b3de1ba2965de929850c383c8ed7665dcae8`.
  Actual merge/main SHA: `a2b5b87466355891d4e4d33320aabdee076a22d4`.
- [PR Backend run 41394572312](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41394572312)
  completed successfully: all 64 unique shards (0–63), classifier and final
  Backend gate passed; changed-test job was appropriately skipped for full scope.
  Programmatic pre-merge verification required latest SUCCESS for each of all
  11 existing required contexts. GitHub reported CLEAN and MERGEABLE. Merge
  used an exact expected head, squash, and no administrator bypass.
- No new local test execution or production deployment occurred. The source
  correction and fresh-process tests were reviewed in the preceding handoff.
  Post-merge main workflows 41397874183 (Supply Chain Security) and 41397874222
  (Production Deployment Policy) are pending; they are not claimed as passed.
- #866 remains unchanged Draft at `998858f31d8c6ff8b8a2fe4b1184d787975efdf3`.
  #869 and #871 remain Draft at their recorded heads; their earlier checks
  against the former main are not automatically validation against updated main.
- Persistent evidence branch remains `docs/hm05-native-source-rehearsal`, #870;
  preceding head `8d0012b189af020f89c5abe7e87c71e0453150e0`. This containing
  commit anchors the updated record. Historical pending/no-merge notes below
  describe prior observations and are superseded by this verified outcome.

Next three priorities: (1) evaluate post-merge main security/policy results;
(2) review and revalidate #869 and #871 separately against updated main before
normal merge; (3) retain #866 isolation until its documented benchmark and
artifact-equivalence criteria are satisfied. Security-owner freshness policy,
authorized independent H&M source review and operational/customer acceptance
remain outstanding. Customer Pilot remains **NO-GO**. No local monitor is running.

## Merge-readiness handoff — 2026-11-02

The owner now authorizes normal merges when engineering validation establishes
readiness. This supersedes historical no-merge authorization notes below; it
does not authorize bypassing protections, deploying, or accepting a customer pilot.
Customer Pilot remains **NO-GO**.

- Existing evidence branch: `docs/hm05-native-source-rehearsal`, PR #870;
  preceding exact head `2ef070e796b13fc12b10b317c86510035fc86b5e`.
  The containing commit anchors this handoff. No duplicate PR was created.
- Reviewed #867 at `78f6b3de1ba2965de929850c383c8ed7665dcae8`:
  six-line model-registration correction, fresh-process regression tests,
  synthetic rehearsal receipt and execution record. No new production behavior
  beyond restoring standalone bootstrap model resolution was found.
- Re-read live branch rules: squash only, strict required status checks,
  resolved review threads, no force push/deletion, all 11 existing required
  contexts. No required approving review count; no bypass was used.
- Marked #867 ready for review under the new authorization. Normal PR event
  triggered [Full Backend run 41394572312](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41394572312)
  on that exact head. Classification passed and all 64 shard jobs were allocated;
  execution is **pending**, not a pass. The earlier manual run 41344854507
  passed all 64 shards and gate. No new local tests were executed in this review.
- No merge or automatic merge was requested while the new required validation
  is pending. #866 remains unchanged Draft; its single paired study is not
  acceptance evidence. No production configuration or security control changed.

Next three executable priorities:

1. Evaluate run 41394572312 on the exact #867 head, investigate actual failures,
   then re-read all required checks and merge normally only if every gate permits.
2. Review #869 and #871 separately against live main, preserving signature-policy
   boundaries and independent source-review holds; obtain applicable ready-state
   hosted validation before considering either merge.
3. Resume #866 acceptance measurements only with exact hosted node/outcome and
   component timing evidence; environment owner must permit the known blocked
   Actions storage destination before independently downloading those artifacts.

Human decisions still required: signature freshness/admission policy from the
security owner, actual independent bilingual H&M source adjudication, operational
acceptance and customer-pilot authorization. Routine valid merges need no further
conversational approval. No background local monitor is running; the GitHub Actions
run above is the actual supported execution currently active.

## Active engineering handoff — 2026-11-02 (Asia/Tehran)

**Customer Pilot remains NO-GO.** Resume from this record and live GitHub.
Review/evidence branch: `docs/hm05-native-source-rehearsal`, existing Draft
[#870](https://github.com/eh3aneba/maritime-claims-platform/pull/870); preceding
head `4df0f8a7948f0e58988ef7b48705c33f997d5a28`. The containing Git commit
anchors this updated handoff. No duplicate PR was created.

Frozen CI candidate [#866](https://github.com/eh3aneba/maritime-claims-platform/pull/866)
remains **Draft**, unchanged at `998858f31d8c6ff8b8a2fe4b1184d787975efdf3`.
Matched baseline main: `fa2c471463f5aecb988f89e791aae359385227e4`.
Both `apps/api` trees are `f239abea5a30d08e3b5d7a3c4508ff91fa55057a`;
application code, tests, lockfiles and the narrow classifier match. #867's
additional bootstrap tests were not silently dropped to make that older run
look comparable; a fresh matched baseline was used instead.

### Completed and actually executed

- One sequential, first-attempt feasibility pair, not the five-pair acceptance
  study. Baseline [41386381744](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41386381744)
  passed **64/64 shards and Backend gate**. Candidate
  [41389632800](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41389632800)
  passed its **collection producer, 64/64 shards and Backend gate** on the
  exact frozen head. No failures, cancellations, retries, source edits or
  Draft-state changes. All 11 required check names were re-read and preserved.
- Observed wall time: **34.42 → 36.65 minutes (+6.49%)**.
  Observed backend runner cost, including candidate producer:
  **511.80 → 470.72 minutes (-8.03%)**.
  These are one-pair elapsed-job observations, not a billing statement or
  established causal/median/p95 improvements. Shard 62 started 3.87 minutes
  after baseline dispatch versus 17.25 after candidate dispatch and became
  the candidate tail. Scheduling, hardware and cache variation remain relevant.
- An offline, read-only timing analyzer and **11 passing fixed-clock synthetic
  regression tests** reject incomplete/failed/skipped/duplicate or wrong-head
  runs, missing producer/gates/steps, malformed timestamps, unmatched source and
  overlapping pairs. Actual incomplete hosted input was rejected; completed
  real receipts reproduce the mixed result. The analyzer cannot grant acceptance.
- Exact-source local collection: **1,591 unique IDs**, nonempty 64-way assignment
  (13–39 IDs per shard). Local digests are reference expectations, not a hosted
  manifest or a claim of 1,591 hosted passes. API artifact metadata is preserved;
  the manifest body and exact hosted node outcomes were not independently read.
- No competing repository execution was observed in polling or the end-of-pair
  recent-activity audit. Four September queued runs still had zero jobs; none
  was cancelled. Global runner contention, image/patch versions and cache parity
  were not independently established. No benchmark-related commit was pushed
  during either run.

The [complete feasibility report](../operations/CI_ACCELERATION_V2_FEASIBILITY_2026_11_02.md)
links source preflight, both job/step receipts, computed metrics, artifact
metadata, interference audit, local reference and exact reproduction commands.

### Current risks and open PRs

**Keep #866 Draft; do not adopt this sample.** The observed wall increase is
above the proposal's 5% median-wall guard number, but one pair does not establish
that median. Five pairs, exact node/assignment/outcome equivalence, cold/warm
classification, 90% collection/selection-component reduction and hosted negative
artifact/producer/rerun evidence remain unverified. Do not lower those criteria.

Detailed Actions storage access is still blocked at the known redirect; no
blocked download was retried, policy bypass attempted or signed URL published.
The candidate archive metadata records expiry **2026-11-03 08:09 Asia/Tehran**;
missing/expired artifacts must fail closed. Local node hashes and combined
selection/pytest step timing do not substitute for missing hosted evidence.

#871 remains the separate read-only OCR reviewer implementation Draft at
`99a12529e35ec506ac49463336f16a08c1592a04`, previously hosted scoped validation
passed. #867 remains Draft at `78f6b3de1ba2965de929850c383c8ed7665dcae8`, with
its earlier full Backend pass preserved below. #869 remains Draft at
`aa82034137b5d765451f607f049f603eeb7dd579`, with no signature-age threshold.
No application/workflow/dependency/production configuration changed in this
execution. HM-05 original packet hashes, source provenance, review holds and
independent-review pending fields remain unchanged. No customer data, external
AI, insurance decision, merge, deployment or branch-protection change occurred.

### Next three priorities / human dependencies

1. Environment owner permits the necessary read-only Actions log/artifact
   destinations through the supported policy workflow; engineering verifies
   exact hosted nodes/outcomes and collection/selection timing. Never bypass
   denied storage access or relabel database-only skips as executed passes.
2. Investigate latency/scheduling and complete the documented repeated paired
   study plus hosted failure/rerun/expiry proof before adoption. Preserve the
   frozen #866, all 64 shards, classifier and all required contexts. No merge or
   review-state change is authorized.
3. Authorized bilingual H&M reviewer performs source-bound adjudication; security
   owner explicitly approves signature-freshness policy before admission changes.
   Original-source holds and Customer Pilot NO-GO continue. Do not self-attest
   expert, operational or customer acceptance.

## Prior execution — published-network validation

**Customer Pilot remains NO-GO.** Resume from this record plus live GitHub.
Current implementation branch: `feat/ocr-independent-review-readback`, exact
SHA `99a12529e35ec506ac49463336f16a08c1592a04`, now Draft
[#871](https://github.com/eh3aneba/maritime-claims-platform/pull/871).
The existing documentation/reviewer branch is
`docs/hm05-native-source-rehearsal` / Draft #870; this containing Git commit
anchors its evidence revision. Its preceding head was
`ce752d8f36ed183088503da4dc018adeaf35290a`.
Fetched main remains `fa2c471463f5aecb988f89e791aae359385227e4`.

### Actual outcomes

- The owner's published replacement environment has an enforced restricted
  policy including the four requested domains. GitHub API and pinned build
  downloads now work. Engineering did not modify or republish configuration.
- #871 was created only after checking for duplicates. At its exact head, five
  non-Backend workflows completed successfully; Full Backend was skipped under
  Draft policy. Hosted frontend contract tests, typecheck, build and the browser
  regression actually executed. Local evidence remains four contract tests,
  five existing backend authorization/workpaper tests, typecheck/build and a
  synthetic bilingual browser test asserting zero API writes. No holds or
  reviewer acceptance records were changed.
- #869 remains Draft at `aa82034137b5d765451f607f049f603eeb7dd579`;
  exact-head hosted readback shows its signature regressions and applicable
  workflows successful, Full Backend skipped. No freshness threshold or
  evidence-admission change was made.
- #867 remains Draft at `78f6b3de1ba2965de929850c383c8ed7665dcae8`.
  Authorized manual Full Backend run
  [41344854507](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41344854507)
  selected all 64 unique shards on that exact SHA. **Completed successfully: all 64 shards and the Backend tests gate passed.**
  Measured dispatch-to-last-job wall time **42.53 minutes**,
  **486.18 shard runner-minutes** (sum of job elapsed durations,
  not a billing statement), **486.33 total job runner-minutes**,
  and **19.08 minutes** between first/last shard starts.
  No failures or reruns. [Exact run/job receipt](../pilot/hm-multidoc-v1/validation/pr867-full-backend-2026-11-01.json).
- The [selected pinned worker rehearsal](../pilot/hm-multidoc-v1/HM05_SELECTED_WORKER_REHEARSAL.md)
  completed through real ClamAV admission, fresh PostgreSQL 18.4 migrations and
  actual worker processing at UID 1000 with read-only/capability restrictions.
  Image configuration digest:
  `sha256:63b5d8850d5ac76cc0bb2b2f8f95a837c8748b05574683dc492566f06318b5da`.
  Tesseract 5.5.3 reproduced the same incomplete transcript as native 5.5.0:
  `5a2304f4b11d628d7694eb38e24d8d335bf8dbf31e0e0b5cb639bc2cd0bd3cd2`.
  The negative token remains, while ` شد.` and ` است.` are omitted. The date
  mismatch includes raster/RTL presentation; it was not normalized or assigned
  solely to OCR. Full source locators, versions, raw output, build identities
  and excluded setup failures are in the linked observation.
- PostgreSQL independently confirmed persistence after worker exit. Readback
  remains `machine_unverified` / `ocr_human_source_comparison_required`;
  zero ClaimFacts and Assessments were created. The final replay passed fresh
  synthetic execution plus nonzero refusals for non-test mode and an existing
  dataset. The original packet's eight checksums and pending review fields
  remain unchanged. Disposable services and temporary private environment
  files were removed. No customer Evidence, external AI, deployment or merge.
- All 11 required check contexts were read from the live main ruleset and
  preserved. #866 remains Draft and untouched at
  `998858f31d8c6ff8b8a2fe4b1184d787975efdf3`.

### Risks and measurement limits

The first worker build inherited restored workspace `0600` source permissions;
non-root migration/import attempts failed and were excluded. Rebuilding from
Git archive's readable source modes resolved setup without root fallback,
changing the repository Dockerfile, or weakening TLS/checksum/source checks.
The session CA adaptation is reproduced in the worker report.

The #867 test tree includes `tests/test_auth_bootstrap_cli.py`, absent from
frozen #866. #866's tests/locks match main, not #867. Concurrent #871 validation
also overlapped #867. Do not call #867's timing an identical-tree CI v2 speedup.
Issue #553 / PR #864's approximately 44-minute median and 505 shard runner-minutes
remain historical references. No candidate benchmark was dispatched here.

Detailed Actions logs redirect to `productionresultssa7.blob.core.windows.net`,
which is denied by the proxy. This newly observed profiling blocker was recorded
once; no retry, configuration change or signed download URL is included in
repository evidence. API job/step timing metadata remains available, but its
combined collection/test step cannot separate those costs precisely.

ClamAV's observed database 28164 dates from 2026-10-25. CLEAN on synthetic input
is not approved freshness policy. Security-owner policy, independent bilingual
H&M adjudication, workpaper content verification/source-resolution authority,
selected-host operational acceptance and customer permission remain outstanding.

### Next three priorities / human dependencies

1. Review completed exact-SHA #867 full regression and #871 scoped hosted
   evidence as Drafts; reconcile new #870 documentation checks on its latest head. No merge or review-state change is authorized.
2. Prepare a matched-main (`fa2c471…`) versus frozen #866 hosted benchmark with
   equal test trees/node hashes, no competing runs and recorded queue/cache
   conditions. Preserve all shards, classifier and checks. Optional per-test
   profiling requires the environment owner to permit the exact Actions log
   destination; do not bypass the policy.
3. An authorized bilingual H&M reviewer must compare the unchanged source and
   transcript and record a source-bound workpaper; the security owner must
   explicitly decide signature-freshness policy before admission changes.
   Engineering cannot self-attest acceptance or clear holds.

Continue this single principal implementation and the existing #870 review
track; do not open duplicate PRs or invent another unrelated workstream.

## Risk-first execution readback — 2026-11-01 (Asia/Tehran)

**Customer Pilot: NO-GO.** This update records observed engineering evidence,
not independent reviewer acceptance or deployment authorization. Existing
human-review holds and all required GitHub checks remain unchanged.

### Exact refs and hosted observations

Fetched `main`: `fa2c471463f5aecb988f89e791aae359385227e4`.
Live GitHub PR pages confirmed these heads and **DRAFT** state:

| PR | Exact observed head | Validation / remaining work |
| --- | --- | --- |
| [#867](https://github.com/eh3aneba/maritime-claims-platform/pull/867) | `78f6b3de1ba2965de929850c383c8ed7665dcae8` | Five successful workflows; Full Backend [41325836131](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41325836131) skipped. No new dispatch started this session. All 64 shards remain unverified. |
| [#869](https://github.com/eh3aneba/maritime-claims-platform/pull/869) | `aa82034137b5d765451f607f049f603eeb7dd579` | Six successful workflows, including signature observation regressions [41331020788](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/41331020788); Full Backend skipped. No signature-age threshold or evidence-admission policy introduced. |
| [#870](https://github.com/eh3aneba/maritime-claims-platform/pull/870) | `1be62517596f24b7b2cd7da1e721fe0ec264b408` (packet revision preceding this status update) | Branch workflow listing after the packet push shows five successful workflows: PostgreSQL 41333132453, deployment policy 41333132426, supply chain 41333132437, performance 41333132412, CI 41333132409; Full Backend 41333132391 skipped. Public run-page inspection did not expose the full run head SHA; exact run-to-commit binding remains to be confirmed through the API. These observations do not validate a later status-update commit. |
| [#866](https://github.com/eh3aneba/maritime-claims-platform/pull/866) | `998858f31d8c6ff8b8a2fe4b1184d787975efdf3` | Untouched; separate hosted shared-manifest benchmark pending. |

### Observed network and selected-worker blockers

Runtime status reports current observations, enforced restricted policy, and
spec/observed revision **1**. Its effective host list excludes `api.github.com`,
`dl-cdn.alpinelinux.org`, `download.osgeo.org`, and `poppler.freedesktop.org`.
Fresh HTTPS probes through the inherited proxy returned **CONNECT 403 Forbidden**
for all four destinations. This is a network-policy denial before GitHub API
authorization, not evidence of insufficient repository permissions. The pending
configuration has not become active. No repeated failing dispatch was submitted.

Once the environment owner applies the supported configuration and access is
verified, the authorized command is:

```bash
gh workflow run backend-premerge.yml \
  --repo eh3aneba/maritime-claims-platform \
  --ref fix/auth-bootstrap-model-registry
```

First recheck that branch against the #867 SHA above. The existing dispatch path
explicitly selects full coverage and allows Draft validation; do not change PR
state, classifier, matrix, required contexts or branch protection. Bind the new
run ID, event, full head SHA and all shard outcomes before claiming success.

Only PostgreSQL and ClamAV images are cached. No worker build was started with
mandatory source destinations denied. Selected worker image digest, engine
version, transcript hash and persisted hold readback are **not measured**.
Preserve TLS, proxy CA, pinned source and artifact verification when building.
Native Tesseract observations are not selected-worker acceptance.

### HM-05 evidence and tests actually executed

The existing [bounded bilingual packet](../pilot/hm-multidoc-v1/reviewer-packet-hm05-2026-11-01/README.md)
is preserved byte-for-byte: all eight `SHA256SUMS` entries passed. Its original
PNG hash is `1eef5de99985ee76048f93b04b7184c9a5daf4b6f33441b36c99e9a850e56d4c`;
the exact persisted transcript hash is
`5a2304f4b11d628d7694eb38e24d8d335bf8dbf31e0e0b5cb639bc2cd0bd3cd2`.
Locators remain HM-05, document version 1, page 1, segment 0, raw machine
lines 3/5. The earlier native reproduction retains `معلوم نیست` but omits
` شد.` and ` است.`. The raster's RTL date presentation differs from the
authored logical date; OCR alone is not established as its cause. No new OCR
execution, transcript repair, date normalization or semantic adjudication occurred
in this readback.

Re-executed against the packet revision: **17 tests passed** using
`python -m unittest scripts.tests.test_hm_persian_ocr_probe
scripts.tests.test_persian_ocr_tesseract_psm_ablation
scripts.tests.test_persian_ocr_local_source_integrity -v`.
These are probe/integrity regressions, not a Docker-engine replay. Reviewer,
authorization and independence fields remain blank; acceptance, hold clearance
and Assessment approval remain false. No new application defect was reproduced.

### Separate #866 benchmark preparation

Issue #553 / PR #864's approximately **44-minute median Full Backend wall time**
and **505 shard runner-minutes** are historical references, not a new baseline.
After full execution is available, record baseline and candidate run IDs, event,
head SHA, actual checkout commit/tree (PR merge refs versus dispatch branch),
runner labels, lockfiles, collection count/hash, and complete 64-shard membership.
Compare equivalent test trees and unchanged required checks; otherwise label the
comparison confounded. Never infer collection equivalence from job success alone.

Use at least three comparable completed runs per arm when runner budget permits.
Report medians plus individual measurements: end-to-end dispatch-to-completion,
queue time, execution wall time, sum of shard job durations in runner-minutes,
total workflow job-minutes including producer/setup, collection/install costs,
retries and failures. Preserve failed attempts separately to avoid selecting only
fast successes. Attribute savings only after confirming identical test coverage;
no speedup is currently established. No #866 edits or dispatches were made here.

### Next three priorities and required evidence

1. Environment owner applies network configuration; engineering obtains #867's
   exact-commit 64-shard result and investigates actual failures without weakening
   controls. Confirm API permissions only after network access succeeds.
2. Build/replay the pinned worker against the unchanged packet; record checkout,
   image digest, engine/language versions, raw transcript hash, exact omissions,
   RTL date observations, source locators and persisted human-review hold state.
3. Authorized bilingual H&M reviewer examines original versus transcript and
   completes a source-bound private workpaper. Independent acceptance remains
   pending; engineering cannot self-attest or clear application holds.

> **Live execution update — 2026-10-25, baseline `main@96772648814397e620accd1d5b50a8515b3ef243`.**
> The product owner adopted the **2026-10-25 Persian strategic review and
> corrective execution plan** as the prioritization policy alongside the
> existing 15 October R0–R7 roadmap. The uploaded review is the planning
> input; this file is the versioned live GitHub status index, not a claim
> of external audit or pilot authorization. Re-verify issue/PR/CI status
> on every new working HEAD. Current pilot release/real customer data:
> **NO-GO**.

## Decision-oriented next 14 days (starting 2026-10-25)

**Outcome to deliver, not merely an implementation:** A claims-handler
completes **one invented multi-document** H&M machinery case through
authenticated manual upload → extraction/processing → evidence and
conflicts/missing records → chronology/technical/financial review →
versioned, source-linked Initial Assessment → correspondence/export.
Record actual human time (including OCR/model wait, review and rework),
source/locator completeness, blockers and final human-approved/rejected
state. No customer Evidence or automatic coverage/settlement decision.

**One principal implementation package plus at most one independent
documentation/review track.** Do not reopen the chain of tiny local
Qwen smoke flags without a specific observed defect. First complete the
three invented H&M cases' independent blinded reference phase; use the
already merged neutral Phase 1 packet and post-blind Phase 2 quote
viewer (#803/#804) rather than building another CLI. Then design six
**versioned, synthetic multi-document** packs (complete, missing,
contradiction, replacement version, scanned/Persian, financial),
with frozen development/held-out split and generic blinded rubrics.
No expert result or reference freeze is currently independently proven.

### Current verified state — separate claim types

| Area / ticket | Code / GitHub evidence (as of 2026-10-25) | Independent operation / expert / customer evidence | Blocker owner role & next acceptance |
| --- | --- | --- | --- |
| R0 scope / #647 | OPEN; owner selected international H&M machinery team, five essential workflow groups, manual authenticated upload, self-hosted AI first | Jurisdiction, actual economic buyer and purchased value unverified; connector OFF must still be proven on chosen deployment | **Product owner**: confirm buyer/jurisdiction and five essentials/exclusions; three to five discovery interviews are planned, not completed |
| #461 — main protection | CLOSED; active ruleset 20842512 has eleven unique required contexts, no bypass, controlled red/green proof | GitHub CI green does not imply independent human review (required approving review count is zero); recheck live ruleset on release SHA | **Technical owner / release approver**: retain mandatory checks and independent sensitive-release signoff |
| #487 — non-root runtime | CLOSED (historical implementation tracking); Web, migration and DB-only worker protections and opt-in isolated Evidence-clone configuration exist | **NOT ACCEPTED on selected host**: API/preflight/OCR worker effective UID/permissions/ClamAV/OCR and existing-volume preservation, rollback evidence missing | **Operations/security owner** under #653: isolated, quiesced Evidence clone rehearsal, effective UID checks, no unsafe `chown`/`chmod`; real volumes untouched |
| #746 — physical Evidence inventory | CLOSED; PR #746 merged at `545c993948f954b8953fa1d108735689176f76f6`; synthetic selected-claim orphan/hardlink audit | **NOT** complete matched independent DB+all-Evidence restore or an all-tenant recovery attestation | **Operations owner**, #653: matched recovery point, independent restore/reconcile, measured rollback |
| #653 — operational release | OPEN; synthetic CI includes substantial deployment, readiness, selected Evidence audits, monitoring and restore helpers | Fresh-host deployment, complete DB+Evidence restore, rollback and received/acknowledged alerts still require independent operator evidence | **Operations/release owner**: nominate selected isolated host, execute and record exercises with owned P0 blockers |
| #764 — historical secret scan | OPEN; previously reported eight historical Gitleaks findings; PR-level security success alone does not resolve historical exposure | Findings require **private** individual classification and equivalent complete-history rescan; credentials, if real, require incident/rotation | **Security owner**: classify findings privately, remediate/attest without publishing values |
| R5 / #752 — local AI | OPEN; #803 neutral Phase 1 and #804 post-blind synthetic model-quote view merged; development Ollama restricted to invented examples | No independent expert labels, multi-document study, runtime identity/egress attestation or approved tenant workflow | **Independent H&M reviewer / technical owner**: freeze blind reference first; compare manual/rules/local LLM on synthetic tasks and decide go/limit per task |
| R5 / #647 — product outcome | Backend/frontend features exist; source/versioned assessment and export capabilities are implemented | No independently observed single-user end-to-end synthetic UI journey with per-stage time and critical error record | **Claims-handler tester / technical owner**: run one complete bounded scenario, fix only measured critical blockers |
| R4 / #652 | Real-server SFTP acceptance remains OPEN but is not an active intake requirement | Pilot v1 excludes SFTP/email/Drive/external AI; prove off-state and no silent fallback on selected configuration | **Security/operations owner**: deployment readback that excluded connectors are OFF |

This is a **state table**, not a claim that an owner has accepted the
assignment. Named people, approved host, real review records and buyer
interviews have not been supplied as acceptance evidence. An OPEN issue
is not proof no code exists; a CLOSED issue is not proof the selected
environment was accepted.

**Next three decision tasks:** (1) obtain blinded independent reference
for the three fixed invented cases and record whether a specialist is
assigned (block if none); (2) prepare the six multi-document synthetic
packs and baseline manual-vs-rules-vs-local-Qwen evaluation protocol,
then run one existing-UI upload→assessment/export case; (3) under #653
and #764, record operations/security responsible roles, selected host,
matched DB+Evidence recovery scope and private historical secret triage.
Avoid making one more validation CLI in place of actual human evaluation.

**Measurement/decision policy:** proposals from the review are >=30%
median handler-time reduction inclusive of review/rework, >=90%
missing-document precision, >=80% extraction acceptance before editing,
semantic source+version+locator verification, abstention/recall,
critical unsupported model assertions **counted even if later rejected**,
real cold/warm latency, total review/compute/support cost and usability.
These are **targets to test**, not achieved results or release gates
without signed acceptance. If the local LLM worsens time or adds no
measured gain versus rules, narrow/stop the LLM task rather than
silently changing acceptance flags or switching to external AI.

**Work-in-progress and follow-up policy:** one principal PR at a time;
a separate narrow documentation/security review is acceptable. Each
report records accepted outcome, exact-SHA evidence, measured
time/quality, blocker and role, and **three next tasks**. Allocate
roughly 40% to handler journey/AI quality, 35% to security/operations,
25% to blinded domain/usability/customer discovery when capacity
permits. R8/R9 remain DEFERRED until purchase/operational demand
is evidenced. A 4–6 week candidate and 8–10 week pilot decision are
conditional planning scenarios, not schedules or guarantees.

--- 

> **Planning reset, 2026-10-15.** This index maps the owner-supplied document
> `SeeClaims_Execution_Roadmap_v1_2026-10-15_FA.docx` to live GitHub
> issues, release gates and evidence. The supplied DOCX is the **normative
> planning reference**; it is not yet committed to this repository.
> This page is a status index, not pilot authorization or a replacement for
> detailed operator runbooks. Do not place customer data or secrets here.

## Source and baseline

- Document version/date: v1 / 2026-10-15 (Persian, 20 pages).
- Document's exact pinned main baseline:
  `762f572c962ed6911c14c0ed0c99f2c49c524431` (after PR #745).
- All technical status must be refreshed from **current** `main` and live
  GitHub PR/issue/check records at the start of each work session.
- **Software implementation / CI PASS / independent operational acceptance
  / customer pilot permission are different states.**
- Pilot target is one H&M machinery claims team, 5–10 consented,
  anonymized or synthetic claims over 30 days, with human authority.
- No auto-permission for customer files, production migration, external AI,
  SFTP or an operational SLA.

## Phase gates and parent issue map

| Phase | Objective | Parent tracking | Gate now |
| --- | --- | --- | --- |
| R0 | Customer, scope, input/AI choice, backlog/status baseline | #25, #647 | **IN PROGRESS — owner decisions pending** |
| R1 | Production non-root, legacy Evidence compatibility, pinned/scanned runtime | #487, #474, #488, #482, #420 | NOT ACCEPTED |
| R2 | Complete DB + all Evidence coherent backup/restore on independent environment | #653 with #487 | NOT ACCEPTED; selected-record audits only |
| R3 | Repeatable fresh-host deployment, alert owners, tenant lifecycle, release/rollback | #653 | NOT ACCEPTED |
| R4 | Prove excluded external connectors remain OFF in selected pilot; SFTP only if separately re-scoped | #652 conditionally | PILOT SCOPE OFF / DEPLOYMENT PROOF PENDING |
| R5 | Independent H&M reference, synthetic multi-document operator journey and task quality acceptance | #647, #752 | NOT ACCEPTED; three short synthetic fixtures only |
| R6 | 30-day controlled, measured, human-reviewed 5–10 case pilot | #647 | NOT STARTED |
| R7 | Commercial contract, costs, deployment reproducibility | #25 | NOT STARTED |
| R8 | Customer-requested extensions with buyer/acceptance criteria | #25 | DEFERRED |
| R9 | Additional claims domains, portfolio analytics, predictions | #25 | DEFERRED |

**Progress metric:** for each phase publish (1) accepted work packages /
all packages and (2) verified exit gates / all required gates. Do **not**
publish a project-complete percentage based on number of merged PRs.

## R0 acceptance tracker (phase 0, not yet passed)

| ID | Required deliverable | State | Owner / next action |
| --- | --- | --- | --- |
| R0-01 | Target organization type, daily user, economic buyer, expensive workflow problem, first 5 essentials, exclusions | **PARTIALLY APPROVED — international (non-Iranian) insurer H&M claims team, vessel machinery focus and five essential workflow groups approved; operating country and other elements pending** | Product owner: confirm jurisdiction, user/buyer, problem, illustrative case and exclusions in `R0_SCOPE_DECISIONS.md` |
| R0-02 | Document entry method, SFTP on/off, external AI mode, connector permissions | **PRODUCT DECISIONS APPROVED — manual Evidence upload, SFTP/email/Drive OFF; local self-hosted AI first and external inference APIs deferred; deployment verification PENDING** | Technical team / independent reviewer: verify connector egress restrictions and demonstrate real local-model inference under #752 before R5 acceptance |
| R0-03 | Unambiguous `README` / #25 / #647 status and software-vs-operations split | **IN PROGRESS** | Technical docs PR; verify latest `main` and correct stale issue references |
| R0-04 | Disposition of old PRs #554, #562, #565, #641 and protected intentional red PR #707 | **COMPLETE (GitHub backlog reconciliation, 2026-10-18)** | Obsolete #554/#562/#565/#641 **closed unmerged** with source-based reasons; #707 remains open, intentional NEVER MERGE; see `R0_LEGACY_PR_DISPOSITION.md` |
| R0-05 | Roadmap ID → tracking issue, owner, dependency, evidence and exit gate | **IN PROGRESS** | This table is the initial mapping; missing accountable humans stay unassigned |

R0 scope decisions **D-R0-01a and D-R0-01b APPROVED by product owner (2026-10-15; international-market clarification subsequently received)**: international (non-Iranian) insurer H&M claims-handling team, vessel machinery damage focus and five essential workflow groups (secure intake/versions; missing-conflicting evidence and chronology; technical/financial review; source-linked versioned Initial Assessment; human-controlled correspondence/export). No named insurer, operating country, validated economic buyer, accepted exclusions, operational capability proof or overall R0 approval is inferred. Selecting the international market also **does not approve or activate OpenAI or any other external AI API**; supported operating jurisdiction, legal/contractual eligibility, customer permission and information-governance gates remain open as part of D-R0-02b.

**D-R0-02a APPROVED by product owner (2026-10-15):** Pilot v1 uses authenticated manual document upload; SFTP, email ingestion and Drive integration will not be enabled. This is an owner-approved scope constraint, **not** evidence that the current production runtime already enforces disabled integrations. **D-R0-02b APPROVED by product owner (2026-10-15):** self-hosted local model inference first, with any OpenAI or other external inference API **deferred until a later separate owner authorization**. This is a roadmap choice only; no local model has yet been shown to run in the pilot candidate, and the production `ai_provider=disabled` default remains until validated. Local OCR/rules alone are not proof of self-hosted LLM readiness. Implementation and security/quality acceptance belong to **#752**. **D-R0-02c APPROVED by product owner:** first *synthetic-only local LLM feasibility* uses the owner's **personal computer**. The owner has now demonstrated Ollama 0.40.4, Qwen3 1.7B loaded at 100% GPU, and a synthetic test whose output **failed source/claim-attribution quality expectations**. This is only personal-device feasibility; no SeeClaims adapter, objective acceptance score, independently verified egress control or customer release exists. See `LOCAL_AI_PC_DEV_PROTOTYPE.md` and #752. **Engineering work continues on GitHub** by owner direction; no further PC interactions are prerequisites for next repository tasks. This device is not the customer pilot host and no insurer claims may be used there. Since SFTP is outside the selected first-pilot scope, controlled real-server acceptance #652 is **not an activation prerequisite for this pilot**, but #652 remains OPEN and becomes required if SFTP is later enabled by an approved scope change.

No R0 completion or downstream gate is claimed before all five are accepted.

## Evidence-backed current snapshot

The table above is the **2026-10-25** authoritative readback. The
following states are carried forward only for traceability: #461 CLOSED
with 11 required contexts; #487 CLOSED for its historical technical
ticket but live non-root API/OCR acceptance still NO-GO under #653;
#746 MERGED/CLOSED, selected-claim inventory proven in synthetic
scratch only; #653 OPEN for independently accepted deployment and
paired restore; #647 and #752 OPEN for user/domain quality; #764 OPEN
for private historical secret triage; #652 OPEN but excluded from the
selected manual-upload pilot. Full-backend workflow success may use
documented scope-based selection; do not claim unexecuted shards ran.

**2026-10-18 R0-04 cleanup:** historical PRs #554, #562, #565 and #641
were inspected against current `main`, commented on and **closed without
merging**; each has a replacement/overlap or stale-protection rationale
in `R0_LEGACY_PR_DISPOSITION.md`. The synthetic #707 proof remains OPEN and
must **never be merged**. The **historical** PR #746 hold has since been
resolved and #746 merged on 2026-10-21; never interpret the old
hold as current. Required-check documentation was updated to
reflect issue #461's dated 11/11 readback and red/green proof; future
release candidates must independently recheck actual ruleset metadata.

## Critical path

For the chosen local-AI-first Pilot v1, **#752 real local model serving + quality/privacy/egress/human-review acceptance is an R5 dependency**. It may be designed before R0 exits, but neither software completeness nor a production customer authorization can be inferred from model selection or a green OCR-only test. **External API integration is outside the initial Pilot v1 critical path** and would need a later scope amendment.

`R0 ACCEPTED` → `R1 accepted production runtime + R2 independent
pair-recovery` → `R3 operator deployment` → `R5 user acceptance`
(+ only relevant active `R4` connectors) → `R6 30-day pilot`.

R1 implementation and R2 design can overlap; final R2 exercise must
repeat against R1's selected runtime and image digests. R3 cannot exit
before R1/R2; R5 can design fixtures in parallel but final acceptance
must use R3's actual candidate.

## Operating rules and next actions

1. Work on one principal change and at most one independent
   review/documentation companion. **Next proof is human H&M reference
   and one synthetic user journey**, not another small model smoke flag.
2. Preserve partial R0: scope/intake decisions are approved; actual
   buyer/jurisdiction, live connector-off readback and independent
   customer value remain blocked until evidenced. R0-04 old draft
   disposition is complete.
3. In parallel have a named operations role select only a synthetic
   isolated host and plan R1/R2/R3 independent recovery/security
   exercises. No production ACL change, `chown -R`, unconditional
   `chmod 777`, or customer data.
4. Validate every relevant PR on **latest exact HEAD** and protected
   checks before squash merge. Do not falsely claim that an omitted,
   skipped or scoped backend shard was executed.
5. Each weekly review reports: accepted deliverables, concrete blocker,
   forecast change and **next three tasks**, with links to exact evidence.
6. Suggested R2 pilot targets **RPO <=24 hours and RTO <=8 hours** are
   planning proposals, **not SLAs** or measured results.

## Native synthetic H&M journey and standalone bootstrap — 2026-11-01

This is a bounded engineering rehearsal, not expert acceptance, selected-host
release acceptance, or permission for customer Evidence. GitHub main remained
`fa2c471463f5aecb988f89e791aae359385227e4`; #866 remained Draft at
`998858f31d8c6ff8b8a2fe4b1184d787975efdf3`, with its backend run skipped.
The API publication/dispatch restriction was unchanged. No workflow was bypassed
or marked green, and no PR was merged or changed to ready-for-review.

**Actual native browser result:** the existing HM-01 multi-document browser
harness passed against isolated PostgreSQL 18.4, native API and document worker,
real ClamAV 1.5.4, the built Next.js frontend and system Chromium. Four invented
DOCX files were uploaded (the first through UI), scanned clean, processed, and
retained as current version 1. The NEW-stage readiness/approval guards held;
TRIAGE activated missing-policy requirements and made the earlier assessment
stale. A new source-bound Preliminary Assessment included all four document
sources without automatic approval. The Unicode XLSX review aid downloaded with
matching immutable snapshot/file-hash headers. Total machine time was **13.799s**;
this is not claims-handler time or a speed/ROI comparison.

The content-free observed record is
[HM-01 native rehearsal](../pilot/hm-multidoc-v1/validation/hm01-native-2026-11-01.json).
It records checkout `cd459b4b0ed97f034669c3e29583ebba60a1479f`, whose application
source tree equals the main application baseline above. The harness assertions
were unchanged; a local launcher supplied system Chromium via Playwright's
supported `executable_path` setting. This was **local native**, not hosted CI or
Docker application-image acceptance. ClamAV clean-file/PING and harmless EICAR
detection controls passed. Freshclam update access was unavailable, so signature
freshness is unverified and no current-malware-coverage acceptance is claimed.
OCR was disabled for these DOCX fixtures; #810's raster Persian negation defect
was not exercised or repaired. External AI and external Evidence adapters stayed
OFF; no customer data or local model was used. Human review/quality, unsupported
model-assertion counts, rework and independent H&M reference acceptance were not
measured. The Assessment remains explicitly preliminary.

**Blocker found and corrected:** the README's standalone
`python -m app.modules.auth.seed` command failed because it imported only a
partial SQLAlchemy model graph; relationship `Vessel` could not resolve before
the first organization query. Application startup had masked this path by
registering the full graph first. Branch `fix/auth-bootstrap-model-registry`
loads the existing metadata registry after configuration validation and configures
it before database work. It adds no role, endpoint, dependency, migration,
insurance-decision behavior or permission. Existing users are not reactivated,
promoted or given replacement passwords. A fresh-process regression failed before
the six-line correction, then passed with real in-memory SQLite persistence,
idempotency, cross-organization email reuse, and early invalid-configuration guards.
The repaired documented command also created one administrator in the isolated
PostgreSQL test database; replay with a different supplied password preserved the
existing identity/hash. Only generated disposable local credentials were used.

Additional local regression evidence includes the existing full MT ORION
nine-document workflow with deterministic fixture-provider responses (not model
quality), simulated role-based review, chronology conflicts, missing documents,
technical/financial review, correspondence and Assessment assertions. Unsupported
Persian PDF export still fails closed without an export record, and Unicode XLSX
remains available; real RTL visual layout and independent bilingual acceptance
under #835 are unproven. The CI safety correction remains separately published at
`cd459b4b0ed97f034669c3e29583ebba60a1479f`; this application fix does not modify
its workflow or #866's files. These roadmap entries are in separate regions to
avoid a conflicting implementation package.

**Verification/publication boundary:** the final combined local suite passed
**16 tests in 41.96s**, including bootstrap/auth/tenant, MT ORION and PDF
source-fidelity controls (two existing deprecation warnings). An earlier combined
invocation stalled and was terminated; it is not counted as passing. The completed
rerun used the supported execution context and bounded stack diagnostics; the
earlier stall's root cause is not established. The application
change must retain the existing full backend, PostgreSQL and other applicable
hosted validation; it is not eligible for an audited test-only shortcut. Hosted
results for this branch have not been obtained. Rollback is reverting the
bootstrap import/configuration and its regression/documentation slice; no data
migration or production operation is involved.

**Next three priorities:** (1) obtain API-capable Draft publication and exact-commit
hosted validation for the CI safety fix and bootstrap correction while preserving
#866's Draft state; (2) dispatch and measure #866 against #553's 44m13s/505.5-minute
hosted baseline, including queues/producer/artifacts; (3) extend measured synthetic
H&M review with independent source-fidelity/human feedback and keep #810/#835/#850,
#653 host/recovery/alerts and #764 private security signoff explicitly unresolved.
Only one automated HM-01 rehearsal was measured here; no arbitrary project
completion percentage, commercial acceptance, or production readiness follows.
