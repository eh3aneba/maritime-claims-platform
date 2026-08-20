# ADR-047 — Pilot exit is manifest-only

Status: Accepted

The in-product exit operation produces an idempotent claim-scoped count manifest and SHA-256 checksum only after the pilot
governance profile is approved. It neither exports record content nor deletes data. Any later export or deletion requires a
separate, approved runbook with retention, legal-hold and authorization checks.
