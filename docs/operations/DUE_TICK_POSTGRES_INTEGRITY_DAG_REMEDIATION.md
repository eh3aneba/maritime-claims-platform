# Due-tick PostgreSQL integrity-DAG performance remediation — engineering gate

Status: **design and evidence only; no production optimization authorized**. Owner issue: [#766](https://github.com/eh3aneba/maritime-claims-platform/issues/766). Pilot recovery/governance: [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653), **NO-GO**.

## Reproducible evidence (synthetic, real PostgreSQL; 2026-11-17)

The approved two-consumer test in `apps/api/tests/test_external_document_source_due_tick_observation_concurrency_postgres.py` retains exactly one winner, one conflict, and one provider metadata call. It uses test-only fixed-label timing and DBAPI aggregate hooks, enabled only with `APP_ENV=test` and `EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST=1`. No SQL, bind parameters, identifying fields, or source content are logged.

| Source / scope | Measured facts |
| --- | --- |
| [PR #945](https://github.com/eh3aneba/maritime-claims-platform/pull/945), PG [run 44048534496](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/44048534496) | Two legacy resolver calls each ran **33,331 successful DBAPI executes**; total **66,662** within the two inclusive resolver frames. Their wall times were **24.658s** and **24.523s**, of which **8.098s** and **8.057s** respectively were inside DBAPI execute hooks. Winning `execute_due_tick_observation` took **65.716s**; losing worker binding lock **73.995s**. |
| [PR #946](https://github.com/eh3aneba/maritime-claims-platform/pull/946), PG [run 44054793473](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/44054793473), job 133941377331 | Within winning worker `b`, legacy resolver ran twice at **33,331 statements/call**. The nested authorization integrity validator ran **four** times at **11,111 statements/call**. Nested checkpoint integrity ran **eight** times at **4,639 statements/call**, restaging integrity **eight** times at **3,203 statements/call**, and change-detection integrity **eight** times at **3,197 statements/call**. Winner execute **47.653s**, losing worker lock acquisition **53.749s**. Five PG tests passed. |

**Accounting rule:** parent/nested counts are *inclusive*. Never add the 11,111 / 4,639 / 3,203 / 3,197 counters together as independent queries. DBAPI `execute` timings exclude portions of ORM identity-map processing, row materialization, Python checks, application logic, and instrumentation; they are neither total Python CPU time nor server-side PostgreSQL execution plans. Variance between hosted runs is expected. Historical exit code 139 remains unexplained.

## Verified path and likely fan-out

- `due_tick_observation_service.execute_due_tick_observation` obtains a binding-level lock, resolves provider lineage, executes a metadata observation, and verifies stored observation integrity before commit. The integrity step independently invokes provider lineage again; it is a **safety boundary**.
- For legacy SharePoint/Drive, `recurring_observation_provider_lineage._resolve_legacy` verifies Evidence Admission Execution, Generation-3 Change Detection, Checkpoint Generation-3, and Generation-3 lineage, each traversing earlier proof chains.
- `evidence_admission_execution_service._ensure_execution_integrity` invokes Admission Authorization integrity; the latter calls `_eligible_observation(..., require_latest=False)` and its historical lineage verification.
- The Generation-3 checkpoint and candidate/change-detection validators call predecessors recursively (including successor restaging, prior checkpoint and change detection). The fan-out is therefore a repeated directed acyclic graph of checks, not a single slow statement.
- Live status, source/claim binding, admission safety, currentness and history attestations are **not interchangeable**. A previously successful digest check cannot silently substitute for a later verification.

## Mandatory evidence before proposing production caching/deduplication

1. **Mutability inventory**: classify every candidate ancestor model as *immutability guaranteed in PostgreSQL* vs *mutable/live*; verify **database constraints/triggers, write and delete paths, migrations, repair/admin operations, retention handling and revocation semantics**. Python naming such as `completed` does not establish immutability. Document proof of append-only enforcement, or mark it mutable.
2. **Transaction and snapshot analysis**: record PostgreSQL isolation level, read ordering, source fingerprint binding and row locks. Under READ COMMITTED, a repeated query can see concurrent changes. Neither a Python `Session` cache nor REPEATABLE READ alone proves currentness; do not silently replace the second integrity pass.
3. **Data-access plan**: favor scoped batching of read-only ancestor fetches, narrowing identity-safe SELECTs and avoiding redundant ORM round trips *while re-executing all substantive checks*. Preserve organization/profile/claim scoping and error types; do not expose cross-tenant rows.
4. **Only if formally justified**, consider transaction-local reuse of cryptographic proof results for **truly immutable and identically bound** ancestor versions. Define cache key by full identity + content/version digest, explicit expiration at transaction end, and invalidation on any mutable ancestor/version/authorization change. No process/global cache, no cross-request reuse. Require separate reviewer/security signoff.
5. **No safety shortcut**: do not remove `ensure_due_tick_observation_integrity`, skip upstream receipt-chain validation, downgrade malware/permission status checks, disable discrepancies, change lock order, drop required checks, mask `exit 139`, raise timeouts as a “fix,” or assert restored pilot availability from green CI.

## Acceptance test matrix for a future, separate code PR

- **Parity**: existing synthetic PostgreSQL two-worker tests still show exactly one success, one conflict, exactly one provider observation and no extra persisted/audit entries; all legacy and SFTP paths preserve current semantics.
- **Mutability adversarial**: changes to authorization, claimant/tenant binding, revocation, profile status, receipt hash, checkpoint state, predecessor completion hashes, source fingerprint and a relevant historical ancestor **between verification points** must fail closed. Include concurrent transactions, distinct Sessions and real PostgreSQL isolation; also test rollback/retry and a stale ORM identity-map instance.
- **Cross-tenant**: forged organization/profile/claim IDs cannot exploit batched or reused ancestor fetches; missing rows must never resolve from a different tenant.
- **Performance**: capture same allowlisted DBAPI-count and wall-time metrics across multiple matched PG runs at the same fixture size and runner class. Report distributions, source-vs-optimized counts, before/after lock hold and conflict wait; do not cherry-pick a single low-latency run or impose arbitrary relaxed timeouts.
- **Protection**: all six exact-head hosted workflows and all eleven required check contexts pass, including Full Backend, actual PostgreSQL concurrency, Supply Chain Security, Production Policy, browser and performance smoke. Never merge behind-base, waived, or incomplete checks.
- **Review**: independent code/security reviewer accepts a concrete transaction-consistency argument and an explicit rollback plan before any production performance patch merges.

## Sequencing and release boundary

1. Freeze this evidence and complete the mutability inventory; identify a single minimal set of immutable ancestor checks to optimize. If immutability is unproven, begin with identity-safe **batched reads without skipping checks**, not memoized validation.
2. Submit a separate production patch limited to a justified optimization, with adversarial real PostgreSQL tests proving fresh revocation and historical tampering remain detectable.
3. Measure under protected CI and review any regressions in provider-lineage integrity or locking. Report benefit and remaining fan-out objectively.
4. Keep issue #766 open until the end-to-end critical path and failure mode have acceptable verified behavior.

**Release is independent:** [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653) still requires a quiesced same-point PostgreSQL + Evidence backup, real isolated restore and rollback, monitoring, security approvals, historical secrets review [#764](https://github.com/eh3aneba/maritime-claims-platform/issues/764), signed-PDF policy [#894](https://github.com/eh3aneba/maritime-claims-platform/issues/894), and independent bilingual H&M OCR review [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810). A faster CI due-tick test is **never** a Pilot GO authorization.
