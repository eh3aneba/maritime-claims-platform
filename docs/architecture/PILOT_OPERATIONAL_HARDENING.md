# Pilot Operational Hardening

Sprint 9H–10C adds an operational control plane around the private design-partner pilot and its production-control follow-up.
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
14. An attested architecture baseline can anchor versioned implementation evidence for five foundational controls.
15. A different Manager/Admin verifies or rejects every control; rejected versions stay immutable and visible.
16. Only five independently verified current submissions permit a frozen verification snapshot, which never authorizes go-live.

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
- Every state-changing operation is appended to the audit trail.

## Deployment use

The controls support a documented rehearsal, bounded private pilot and architecture baseline. Operators must still implement
the target infrastructure, independently verify evidence, perform recovery and security tests, validate incident contacts and
obtain the organization’s own security, privacy, legal and production-go-live approvals.
