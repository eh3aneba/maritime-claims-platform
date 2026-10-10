# Pilot v1 — release-candidate evidence record and operator gate

Tracking: [Pilot P0 operations #653](https://github.com/eh3aneba/maritime-claims-platform/issues/653), scope [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647). Related: ruleset [#461](https://github.com/eh3aneba/maritime-claims-platform/issues/461), SFTP [#652](https://github.com/eh3aneba/maritime-claims-platform/issues/652) and [#656](https://github.com/eh3aneba/maritime-claims-platform/issues/656).

## Boundary

The standard-library `scripts/pilot_rc_gate.py` tool creates a NO-GO draft and validates **record completeness**. It does not check a live host, inspect evidence contents, query GitHub, activate a ruleset, approve customer data or authorize production. Even a structurally complete record is **not** a GO decision. A named authorized operator must independently verify the supporting artifacts and approve the controlled pilot separately.

## Prepare the release candidate

1. Freeze **one exact full commit SHA** for the release (not an approximate branch name), images and allowed controlled test environment.
2. Observe the actual Alembic revision of the deployed database and compare it to the repository migration head. The current main migration code has revision `0224_obs_refresh_recovery_anchor`, but the record must use the deployed release's verified revision.
3. Record immutable image references for API, Web, Worker, Postgres and ClamAV, using `repository/image@sha256:<64 lowercase hex>`. A mutable tag or a local unqualified image ID is insufficient. Do not invent a digest.
4. Identify the secure configuration contract and known-limitations record **by reference**, without copying credentials.
5. Use synthetic, anonymized or explicitly approved evidence only; this record never licenses live customer claims.

## Create a draft

```bash
python scripts/pilot_rc_gate.py init --output /secure/pilot-releases/rc-001.json --release-sha "$(git rev-parse HEAD)"
```

The file is created exclusively, without overwriting a previous release record. Every proof begins as `pending`, and all image digests, reviewer identities, timestamps and evidence references remain empty until **observed**. Keep the actual record in an access-controlled location, not automatically in the repository.

## Evidence required before record completion

| Group | Required independent evidence |
|---|---|
| Repository protection | Active main ruleset readback **and** disposable failing-required-check proof (#461), not merely merged documentation |
| Controlled real SFTP | Governed real OpenSSH + real PostgreSQL v1→N+1→next unchanged observation, plus restart/replay (#652/#656) |
| Fresh host | Clean deployment, migrations/preflight, browser/operator H&M machinery-claim journey |
| Recovery | Validated database backup, **matching evidence/storage recovery point**, full restore drill, rollback drill |
| Operations | Named owner and escalation for worker/queue/scanner/storage/backup-age monitoring; tenant onboarding/offboarding |
| Exact-head build gates | Full Backend, CI, PostgreSQL concurrency, Supply Chain, Operational Performance and Production Deployment Policy on exact candidate SHA |

Each individual proof must include `result: pass`, an immutable/accessible `evidence_ref`, a responsible `owner`, and UTC `observed_at_utc` in `YYYY-MM-DDTHH:MM:SSZ`. These are human attestations; the command does not attest to their truth.

## Fail-closed completeness check

```bash
python scripts/pilot_rc_gate.py check /secure/pilot-releases/rc-001.json --expected-sha "<independently-verified-full-release-SHA>"
```

A missing/mismatched commit, unpinned image, missing recovery evidence, pending proof or malformed record returns a **nonzero** exit code and `NO-GO`. A complete record prints `RECORD COMPLETE` and explicitly warns that this is not release authorization. Cross-check the supplied SHA against the deployed artifact and linked CI run head; operator-supplied strings alone are not trustworthy evidence.

## Independent exact-SHA GitHub CI metadata observation

The release-record gate above accepts human-attested references and does **not** query GitHub. To reduce the risk of mistaking a stale/failed/skipped run for a PASS, collect a separate exact-head metadata observation with the standard-library helper:

```bash
# Requires GitHub Actions read permission, e.g. a scoped GITHUB_TOKEN
python scripts/pilot_ci_evidence.py \
  --repo eh3aneba/maritime-claims-platform \
  --sha "<verified-exact-40-character-candidate-SHA>" \
  --output /secure/pilot-releases/rc-001-ci.json
```

The output is created exclusively, with no overwrite. It records only the supplied full commit SHA, six required workflow names, latest matching run IDs/attempts, pass/not_pass/missing outcomes, and canonical GitHub run links. **Any missing, skipped, failed, pending or in-progress run yields an incomplete result and a nonzero exit code.** API/network failure fails closed; the token, raw API response, remote secrets and customer data are never written to the observation record. For a private repository, provide a read-scoped GitHub token as an environment variable; never commit it.

**Release-identity rule:** a passing pull-request head is not automatically a passing subsequent **squash-merged main commit**; the hashes differ. Collect and verify CI evidence for the *exact deployed commit* and its corresponding images. Record the observation as an evidence reference only after a named reviewer independently checks the runs and logs. The tool cannot attest deployment, actual database migration, operational controls, backup, scanner readiness, real SFTP proof, repository protection, or human approval. **CI METADATA COMPLETE is not a Pilot GO.**

## Verify whether Full Backend really ran (without triggering it)

A successful `Full Backend Pre-Merge` **workflow** can be a valid, intentional path-scoped result with **zero executed Backend test shards**. Its aggregate `Backend tests` job is green after `Record workflow-only backend bypass`. This is correct for narrow operational/documentation changes but must **never** be described as a 64/64 Backend validation.

After independently recording a workflow run ID corresponding to the exact commit under review, inspect its *actual jobs and steps* (read-only; no test dispatch or re-run):

```bash
python scripts/pilot_backend_execution_evidence.py \
  --repo eh3aneba/maritime-claims-platform \
  --sha "<exact-40-char-candidate-SHA>" \
  --run-id "<observed-Full-Backend-workflow-run-ID>" \
  --output /secure/pilot-releases/rc-001-backend-jobs.json
```

The exclusive, privacy-safe metadata record distinguishes precisely `scoped_skip_verified` (**0** executed shards, intentional) from `full_64_shards_pass` (**64/64** independent successful shard jobs). It validates workflow name, exact SHA, run attempt, the success/skip status of classifier, aggregate steps, distinct shard IDs, and complete matrix. Missing, failed, cancelled, stale-attempt or malformed jobs fail closed. It does not copy raw job logs, claim data or GitHub access tokens.

**For a final release-candidate record only**, when a real full Backend run is explicitly required, use the same read-only checker with `--require-full` and a new output path: an intentionally scoped skip then returns an incomplete (exit 1), not a false full-suite PASS. This does **not** change CI's selective triggers or require running expensive tests for every operational PR. A workflow-level green result from `pilot_ci_evidence.py` is *not* a substitute for this separate job-level matrix proof. Nor is 64/64 proof equivalent to Pilot release authorization or deployed-image attestation.

## Manual GO/NO-GO remains mandatory

The accountable release owner must separately record decision, reviewer, timestamp, environment/tenant, permitted data class, limitations, backup/rollback owner and go-live/abort conditions. Keep Pilot v1 bounded to one H&M machinery claims team, 5–10 permitted claims, 30 days, mandatory human review and no autonomous claim decision. If any P0 gate is unresolved, **NO-GO**.

See [backup/restore instructions](BACKUP_RESTORE.md), [deployment checklist](DEPLOYMENT_CHECKLIST.md) and [Pilot v1 scope](https://github.com/eh3aneba/maritime-claims-platform/issues/647).

**This slice delivers only the record gate and regression tests. It does not claim the real fresh-host, storage restore, SFTP lifecycle, ruleset mutation or operations exercises have been performed.**
