# Pilot v1 — controlled tenant onboarding, offboarding and data custody

Tracking: [Pilot operations #653](https://github.com/eh3aneba/maritime-claims-platform/issues/653), [Pilot scope #647](https://github.com/eh3aneba/maritime-claims-platform/issues/647). Dependencies: [Protect main #461](https://github.com/eh3aneba/maritime-claims-platform/issues/461), [real SFTP #652](https://github.com/eh3aneba/maritime-claims-platform/issues/652).

**Status: operator procedure only. No actual tenant has been enrolled or removed by this document.** A green CI or completed worksheet is not permission to ingest customer claims. Keep the Pilot NO-GO until the independent #653 release criteria are met and an accountable release owner approves one bounded environment and data class.

## 0. Authority, scope and safety

- Pilot v1 means **one organization / one H&M machinery claims team**, at most **5–10 explicitly permitted claims over 30 days**, supervised by human handlers. No automated coverage, causation, liability, quantum, settlement or fraud determination.
- Name three *independent* responsibilities: (1) accountable pilot/release owner, (2) tenant identity/admin owner, and (3) evidence retention, security and recovery owner. Record their organizational identities in the private change ticket, not in a public GitHub Issue.
- Agree the permitted data classification and provenance **before receiving any files**. Use MT ORION or synthetic/anonymized fixtures until live claim data is expressly authorized under the organization's confidentiality and security arrangements.
- Freeze one full 40-character release SHA, immutable API/Web/Worker/Postgres/ClamAV image digests and deployed Alembic revision. Do **not** infer deployed identity from a passing PR SHA or a local image tag.
- Keep all operator signoffs, exact asset IDs, hostnames, organization/user identifiers, personal data, credentials, MFA seeds and evidence contents in an access-controlled operator system. Public tickets contain only opaque references, result codes and a non-sensitive reason.

## 1. Pre-onboarding GO/NO-GO — mandatory stop before user creation

| Independent check | Operator evidence to record | On failure |
| --- | --- | --- |
| Candidate/build | Exact release SHA, image digests, migrations and exact-release CI security/policy results | **NO-GO** |
| Repository governance | Active `Protect main` **11/11** required contexts **and** disposable failed-required-check merge-block proof (#461) | **NO-GO** |
| Environment | Real clean-host build/preflight, loopback port policy, TLS/reverse-proxy/firewall review, 11 Compose service readiness; real ClamAV tested | **NO-GO** |
| Recovery | Matched DB/Evidence recovery point, encrypted off-host copies, **actual** independent restore and bounded rollback with owners | **NO-GO** |
| Monitoring | API/DB/worker/scheduler/observer/review/scanner/storage/backup-age/authentication/latency rules, delivered test alert, acknowledged escalation | **NO-GO** |
| SFTP | If enabled: independently approved real-server v1→N+1 qualification, algorithm and host-key record, negative tests (#652). Otherwise **disabled** | **NO-GO for SFTP** |
| Scope and authority | Named H&M handlers, permitted evidence class and retention/legal-hold owner, signed 30-day/5–10-claim boundary | **NO-GO** |

A test in an ephemeral GitHub runner, CI synthetic backup, simulated human actor, or operator-entered `pass` string is **not** a substitute for independent operating-host proof. See [release candidate gate](PILOT_RELEASE_CANDIDATE.md), [deployment checklist](DEPLOYMENT_CHECKLIST.md), [backup and restore](BACKUP_RESTORE.md) and [SFTP constraints](SFTP_PRODUCTION_RUNTIME.md).

## 2. Controlled initial organization and identity

**Owner:** tenant admin with separate release-owner approval.

1. Obtain an approved *new tenant* change request; establish uniqueness, authorized domain and data-custody jurisdiction. Verify that there is no cross-tenant seed, default shared password or existing customer copy.
2. The repo exposes **no general-purpose organization-create endpoint** via `apps/api/app/modules/organizations`; organization provisioning therefore requires a reviewed, tenant-specific bootstrap process from the responsible operator. **Do not fabricate a `POST /organizations` API, direct database insert command or production `demo-seed` procedure.** Record actual supported provisioning steps and observed resulting organization identity in the private change ticket. If no reviewed bootstrap method is available, stop onboarding.
3. Create the **minimum** initial Admin through a reviewed provisioning method. The implemented `POST /users` route requires an *already authenticated same-tenant Admin*; it is not first-tenant bootstrap. Before using it for subsequent users, prove organization scoping with a readback; do not use credentials from another tenant.
4. Enable and read back the tenant MFA policy at `/api/v1/auth/mfa-policy` using an authorized Admin; require MFA for privileged/claims users per the security baseline. Check completed TOTP/WebAuthn/approved enterprise identity assurance, not merely an enrolled-but-unverified factor. Securely provision recovery with separation of duties.
5. Create only necessary subsequent users using the same-tenant Admin route `POST /api/v1/users`. The current application role enum is **`admin`**, **`claims_manager`**, **`claims_handler`**. Do not invent `viewer` or `superadmin` permissions. Authorize least privilege and compare the response's organization and role to the approved change request.
6. Verify a user login, current identity `/api/v1/auth/me`, session `/api/v1/auth/session`, MFA step-up for privileged action, and denial of a cross-tenant operation with test data. A successful enterprise SSO authentication alone must not grant application organization membership or role authority.
7. Capture *only* synthetic bounded success/failure, timestamps, issue IDs and masked audit-log evidence; do not log passwords, session cookies, MFA codes, raw response bodies or identity tokens.

**Stop rule:** if bootstrap, role isolation, MFA assurance or revocation cannot be demonstrated, keep this organization in a closed synthetic-only state.

## 3. Data/AI governance and external integration enablement

**Owner:** H&M claims lead + evidence custodian + security reviewer.

1. Specify intake routes explicitly: permitted manual evidence upload; email/SharePoint/Google Drive/SFTP integrations are **disabled until separately qualified and approved**. External SFTP approval requires #652 even if localhost OpenSSH CI is green.
2. Record approved file-size/type limits, malware scanner status, quarantine and Evidence object-store custody, access controls, source-linked provenance, snapshot integrity and controlled processing-release authority. Verify a harmless synthetic clean file and a safe scanner challenge through the existing approved acceptance test—not by uploading real malware.
3. Set the organization retention policy through the implemented `/api/v1/retention/policies` Admin + MFA route only after legal/privacy review. Validate policy version/readback; decide **legal holds before** any disposal eligibility. Retention is not a license to delete evidence without the release/authorization workflow.
4. Set external AI use to **disabled** for the initial synthetic Pilot unless privacy/security owner expressly approves a provider and permitted evidence class. Test that machine suggestions require human review and no assessment overwrites immutable approved facts.
5. Record named reviewer, reserve/quantum authority and escalation; no final claim decision without a human.

## 4. One controlled operator rehearsal — synthetic only

**Owner:** actual Pilot claims handler, observed by release owner.

1. Authenticate as the new-tenant handler with MFA; use only its own synthetic H&M machinery claim.
2. Run `intake → Evidence/antivirus custody → missing/conflict review → chronology → technical/financial assessment → versioned Initial Assessment → correspondence/export`.
3. Attempt a forbidden cross-tenant document read and an unauthorized assessment/processing action; require deny-and-audit without exposing another tenant's IDs or bytes.
4. Confirm AI suggestions are **draft-only**, reviewer changes produce source-linked audit/snapshot lineage, and a prior approved version does not silently change.
5. Record elapsed time against a *measured* handler baseline, accepted/incorrect suggestions, missing-document precision, major usability blockers, operator assistance and final owner decision. See [design-partner protocol](../pilot/DESIGN_PARTNER_PILOT_PROTOCOL.md). Do not claim target metrics before measurements.
6. Run one bounded backup/restore and alert-delivery acknowledgement in the **authorized synthetic host**; connect evidence references to the exact frozen release SHA.

## 5. Controlled user departure and tenant offboarding

**Owner:** tenant Admin + security/retention and release owners. Offboarding **is not deletion**.

1. Open an approved exit ticket naming the effective time, organization-specific scope, export recipient/format and identity owner. Trigger a NO-GO/escalation if any custody or legal-hold facts are unknown.
2. **Stop new ingestion and background refresh first**: disable each approved recurring external-evidence schedule through its governed disable flow (if present); stop or revoke SFTP/secret references and external integration grants through their **provider-controlled approved process**. Confirm queued/ongoing jobs and in-flight releases are drained or safely quarantined. Never assume a disabled schedule immediately cancels an already-dispatched execution.
3. After independent approval, an Admin with **current verified MFA** submits `POST /api/v1/users/{user_id}/deactivate` with a privacy-safe opaque `change_ticket_ref` and the exact confirmation `DEACTIVATE_USER`. The application marks that **same-tenant user inactive**, revokes all currently recorded unrevoked local `AuthSession` rows in the transaction and records one bounded audit event; an inactive user cannot start a fresh application login or use an existing token. The action blocks self-deactivation and cross-tenant targets. Check the response's `sessions_revoked` and `newly_deactivated` fields and verify denial of previous test sessions. Repeat calls are idempotent. **This does not revoke upstream enterprise SSO/SCIM sessions, provider tokens, integrations or external data-access grants**; the identity and integration owners must revoke those separately and independently verify offboarding. The older `POST /api/v1/auth/sessions/{session_id}/revoke` route remains valid for targeted single-session emergency revocation.
4. Preserve document/audit/assessment versions and evidentiary provenance. Produce an authorized data return/export using the existing controlled claim-pack/export workflow **only if scope and completeness are independently verified**. Never copy private Evidence to GitHub CI artifacts or a public ticket.
5. Obtain retention and legal-hold review per claim **before** considering disposal. Use the application's governed disposal dry-run, approval, quarantine, physical execution and closure only when those routes' preconditions, MFA, human approvals and legal policy are met. No `docker compose down -v`, direct S3 object purge, SQL `DELETE`, or unreviewed volume removal in a customer environment.
6. Reconcile database, Evidence store, backups/off-host copies and external providers. Record disposition separately (retained/returned/pending-disposal/verified-destroyed) and legal hold; **pending backups or legal holds cannot be marked destroyed**.
7. Confirm owner-reviewed inaccessible user sessions, revoked integration credentials, disabled schedules, no accidental cross-tenant impact, and preserve a bounded, non-sensitive offboarding audit record. Close the ticket only after independent readback.

## 6. Minimal privacy-safe operator evidence worksheet

Store this *privately* (not committed or appended to GitHub comments). Every line must include an **observed** result, a named internal role, UTC timestamp and an opaque immutable evidence reference; blank or merely claimed results remain pending.

| Gate | Result (pending/pass/fail) | Owner role | UTC observed | Private evidence ref |
| --- | --- | --- | --- | --- |
| Release/11-of-11 main checks/failing-check enforcement | pending | | | |
| Independent clean-host deployment + exact image SHA | pending | | | |
| Matched off-host DB/Evidence restore and rollback | pending | | | |
| MFA and same-tenant role binding | pending | | | |
| External integrations disabled or real SFTP approved | pending | | | |
| Retention/legal-hold version and Evidence custody | pending | | | |
| 11 monitoring signals + delivered and acknowledged alerts | pending | | | |
| H&M synthetic full operator journey, AI human review | pending | | | |
| Disabled schedules and all sessions/integrations on exit | pending | | | |
| Return/hold/disposal and backup reconciliation | pending | | | |

**Decision:** `NO-GO` until all applicable independent proofs are complete, release-owner approval is separately signed, and #461/#652/#653 exit requirements are met. This runbook does not create, update, or delete tenant resources; completing the template cannot automatically transition a Pilot to GO.
