# Pilot Operational Hardening

Sprint 9H–10E adds an operational control plane around the private design-partner pilot and its production-control follow-up.
It does not certify production readiness or automate compliance decisions.

## Control flow

1. A user captures the eight deployment-control results as a hashed readiness snapshot.
2. Only a Manager/Admin can attest a snapshot, and only when every control passes.
3. A Manager/Admin runs idempotent monitors that store bounded counts and alerts, never claim content or secrets.
4. Operational findings enter a human-owned incident ledger with explicit acknowledgement and resolution.
5. External material is proposed against an invitation and approved or rejected by a different Manager/Admin.
6. Pilot governance records purpose, basis, owner, retention, residency and exit ownership before approval.
7. An approved profile permits a claim-scoped exit manifest containing counts and a checksum. It does not export content or delete records.
8. An attested readiness snapshot anchors a rehearsal with evidence references and owned remediation findings.
9. Only a Manager/Admin can freeze the final Go/No-Go snapshot; Go requires all eight controls to pass and every finding to be resolved.
10. A completed Go rehearsal permits one bounded private-pilot execution. A Manager/Admin must start and complete it.
11. Case runs store measurements and bounded references, not claim content; observed P0–P3 gaps retain an owner and due date.
12. Proceed is blocked while any P0 gap remains unresolved, and the final Proceed/Pause/Stop snapshot is immutable.
13. A completed pilot can anchor a nine-domain production-architecture baseline. Missing and partial controls remain visible in the attested snapshot.
14. An attested architecture baseline can anchor versioned implementation evidence for all nine architecture controls; historical five-control gates retain their original profile.
15. A different Manager/Admin verifies or rejects every control; rejected versions stay immutable and visible.
16. Only independently verified current submissions for every control in the gate's immutable profile permit a frozen verification snapshot, which never authorizes go-live.
17. A completed `architecture_v2` gate may anchor a seven-check operational acceptance with named release, rollback, incident and support owners and a bounded UTC-aware change window.
18. Operations and risk approvals require two different Manager/Admin users, both different from the requester.
19. Only an Admin can record Authorize or Hold; authorization expires at the end of the change window and still performs no deployment or traffic action.

## Security boundaries

- Tenant filters apply to every operation.
- Readiness and exit snapshots use canonical SHA-256 hashes.
- Direct portal publication is rejected; privileged or restricted sources never enter the proposal queue.
- Monitoring metrics exclude subject lines, bodies, evidence text, participant details and credential references.
- Exit manifests explicitly record `content_included: false` and `deletion_performed: false`.
- Rehearsal evidence accepts only bounded `artifact://`, `runbook://`, `ticket://` or `monitor://` references.
- Completed rehearsal evidence, findings and decision hash are immutable.
- Completed pilot outcomes and attested architecture baselines are immutable canonical SHA-256 snapshots.
- Pilot metrics explicitly contain no claim narrative, evidence text or personal data.
- Architecture attestation is a reviewed design baseline, never a deployment or production certification.
- Implementation submissions contain bounded references rather than secrets or raw infrastructure artifacts.
- Submitter/reviewer separation is enforced per control; verified submissions and completed gates are immutable.
- Operational checks, approvals and final decision are separately retained; rejected or held attempts permit only a fresh append-only attempt.
- Every operational decision summary states `deployment_performed: false`, `traffic_enabled: false`, `production_certification: false` and `external_ai_authorization: false`.
- Every state-changing operation is appended to the audit trail.

## Deployment use

The controls support a documented rehearsal, bounded private pilot and architecture baseline. Operators must still implement
the target infrastructure, independently verify evidence, perform recovery and security tests, validate incident contacts and
obtain the organization’s own security, privacy and legal approvals, and execute deployment/traffic changes through a separate authorized change process. External AI requires its own activation and evaluation gate.
