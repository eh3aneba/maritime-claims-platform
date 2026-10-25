# SeeClaims — Execution Roadmap v1 | Status and gates

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
