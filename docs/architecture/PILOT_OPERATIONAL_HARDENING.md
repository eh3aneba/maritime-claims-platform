# Pilot Operational Hardening

Sprint 9H–9L adds an operational control plane around the private design-partner pilot.
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

## Security boundaries

- Tenant filters apply to every operation.
- Readiness and exit snapshots use canonical SHA-256 hashes.
- Direct portal publication is rejected; privileged or restricted sources never enter the proposal queue.
- Monitoring metrics exclude subject lines, bodies, evidence text, participant details and credential references.
- Exit manifests explicitly record `content_included: false` and `deletion_performed: false`.
- Rehearsal evidence accepts only bounded `artifact://`, `runbook://`, `ticket://` or `monitor://` references.
- Completed rehearsal evidence, findings and decision hash are immutable.
- Every state-changing operation is appended to the audit trail.

## Deployment use

The controls support a documented pilot rehearsal. Operators must still collect infrastructure evidence,
perform recovery tests, validate incident contacts and obtain the organization’s own security, privacy and legal approvals.
