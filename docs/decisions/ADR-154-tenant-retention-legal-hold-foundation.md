# ADR-154: Tenant retention and legal-hold foundation

## Status
Accepted for Phase 17.2-A implementation.

## Context
The platform already preserves claim and evidence history with tenant scoping, soft deletion and restrictive foreign keys. Enterprise readiness now requires explicit retention governance before any archival or destructive disposal capability can be considered.

A retention deadline is not, by itself, authority to destroy claim material. Claims may remain subject to litigation, regulatory, contractual, recovery or other preservation requirements after an ordinary retention period has elapsed. The platform therefore needs a preservation-first decision layer that can fail closed and remain auditable.

## Decision
Phase 17.2-A introduces three bounded controls.

1. **Immutable tenant retention-policy versions.** Each version pins closed-claim and evidence retention periods, enabled/disposal flags, a deterministic policy hash and the previous policy hash. The latest version is authoritative. If the latest version is disabled, there is no active policy and disposal eligibility fails closed.
2. **Claim-scoped legal holds.** Local application Admins can place preservation holds with an explicit source and reason. Multiple holds may coexist. Original hold facts are append-only; release fields can be populated once and remain auditable. Any active hold blocks disposal eligibility.
3. **Read-only disposal eligibility preview.** The platform evaluates final claim status, current tenant policy, claim age, latest evidence age and active legal holds. It returns blocking reasons and the earliest possible eligibility timestamp. It does not archive, delete, purge, soft-delete or mutate claim/evidence content.

The retention anchor is conservative: the claim `updated_at` timestamp is used for the claim window, while the evidence window starts from the later of the claim update and the newest evidence update. Subsequent claim/evidence activity therefore moves eligibility later rather than earlier.

## Authority and security boundary
- Database tenant membership remains authoritative.
- Policy creation and legal-hold placement/release require local Admin authority and pass the current tenant MFA policy check.
- Claims Managers may read policy/hold history; authenticated claim users may request their own tenant-scoped eligibility preview.
- A policy cannot override an active legal hold.
- Missing or disabled policy state fails closed.
- Open/non-final claims fail closed.
- `disposal_enabled=false` fails closed even when retention periods have elapsed.
- No worker, endpoint or storage adapter performs destructive disposal in this phase.

## Consequences
This phase deliberately separates **eligibility** from **execution**. A later tranche may add controlled archival/disposal only after it can consume this decision layer, require stronger approval/reconciliation controls, prove object/row deletion completeness, and preserve an independent audit receipt without weakening legal holds.

Automated legal-hold signal ingestion is also deferred. Phase 17.2-A establishes the authoritative hold state and API that future litigation/regulatory automation can propose into without making an external signal self-authorizing.

## Rejected alternatives
- **Delete automatically when the retention timer expires.** Rejected because time expiry is not preservation authority.
- **One mutable retention row per tenant.** Rejected because policy history and exact lineage would be lost.
- **A single boolean `legal_hold` on Claim.** Rejected because concurrent holds, sources, reasons and release history would not be independently auditable.
- **Hard-delete first, audit later.** Rejected because destructive execution must not precede the governance boundary that determines whether destruction is permissible.

## Follow-up
Phase 17.2-B should build automated legal-hold proposal/activation controls on top of this foundation. Controlled archival/hard disposal should remain a separately reviewed tranche after preservation automation is mature.

Refs #25, #292.
