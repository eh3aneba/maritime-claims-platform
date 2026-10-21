# SeeClaims — Execution Roadmap v1 | Status and gates

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
| R4 | Selected active external connectors; SFTP only if in pilot scope | #652 conditionally | DECISION PENDING |
| R5 | Three case fixtures, operator journey, financial/domain/output acceptance | #647 | NOT ACCEPTED |
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

At this reset:
- **#461 CLOSED:** branch-protection evidence records 11 mandatory contexts
  with no bypass actors; do not re-open without a new defect.
- **#487 OPEN:** CI synthetic, restricted, non-root API/worker Evidence/OCR
  and rollback tests do **not** establish compatibility with existing
  customer-host ACLs or production non-root runtime.
- **#653 OPEN:** no complete independently hosted, quiesced DB **plus**
  Evidence snapshot/recovery and operator-signoff proof is established here.
- **#652 OPEN:** Phase 17.6 SFTP software is feature-complete, but real
  controlled server acceptance is separate and only a pilot prerequisite if
  the connection is **enabled**.
- **#647 OPEN:** pilot scope and human/operator exit criteria; release and
  customer permission remain gated.
- **PR #745 MERGED:** bounded read-only DB-to-Evidence selected-record
  integrity audit, not full recovery.
- **PR #746 OPEN at reset:** orphan-file inventory branch linked to R2;
  exact-head Full Backend workflow concluded failure at first check. Keep
  **unmerged** until diagnosed, R0 sequencing reviewed and protected
  required gates pass.
- **#474 / #488 / #482 / #420 OPEN:** pin and scan exact selected
  production/base/third-party images and reconcile dependencies.
- **#553 OPEN:** measure any remaining CI optimizations; avoid equating
  workflow PASS with 64 actual executed backend shards.

**2026-10-18 R0-04 cleanup:** historical PRs #554, #562, #565 and #641
were inspected against current `main`, commented on and **closed without
merging**; each has a replacement/overlap or stale-protection rationale
in `R0_LEGACY_PR_DISPOSITION.md`. The synthetic #707 proof remains OPEN and
must **never be merged**. PR #746 remains ON HOLD with its exact-head Full
Backend workflow failure. Required-check documentation was updated to
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

1. Work on one principal change and at most one review/documentation
   companion. First current priority: **R0-01 / R0-02 product decision**.
2. Once the product owner confirms scope, close R0-03 docs and R0-04 old
   draft disposition, then R0-05 accountable gate mapping.
3. Only then start technical `R1-01` plus design `R2-01`. No production
   ACL change, `chown -R`, unconditional `chmod 777`, or customer data.
4. Validate every relevant PR on **latest exact HEAD** and protected
   checks before squash merge. Do not falsely claim that an omitted,
   skipped or scoped backend shard was executed.
5. Each weekly review reports: accepted deliverables, concrete blocker,
   forecast change and **next three tasks**, with links to exact evidence.
6. Suggested R2 pilot targets **RPO <=24 hours and RTO <=8 hours** are
   planning proposals, **not SLAs** or measured results.
