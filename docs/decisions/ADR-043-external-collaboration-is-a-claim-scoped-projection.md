# ADR-043: External collaboration is a claim-scoped projection

## Status

Accepted

## Decision

External participants do not become internal users. They receive expiring, revocable access to a projection of one claim through hashed invitation and session secrets. Only explicitly permitted summary fields and manually published item metadata are visible.

External submissions require internal human review before becoming claim correspondence. Attachment manifests never become evidence without the quarantine and malware-admission path.

## Consequences

- Internal financial, AI, audit, privileged and tenant-wide data stays outside the portal boundary.
- Compromised invitation/session secrets have bounded time and claim scope.
- Invitation replay and revoked/expired sessions fail closed.
- Future raw-file sharing requires a separate download authorization and redaction design.
