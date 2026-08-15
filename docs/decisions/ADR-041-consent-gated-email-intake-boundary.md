# ADR-041: Email ingestion is a consent-gated staging boundary

## Status

Accepted

## Decision

Inbound email enters a tenant-scoped staging queue through a provider-neutral authenticated webhook. Connections require explicit consent and bounded retention. Tokens are generated once and stored only as SHA-256 hashes.

Claim references create suggestions only. A human must confirm the claim link and record a reason before the message becomes inbound claim correspondence. Attachment bytes are rejected from this boundary; only manifests are recorded until the existing quarantine and malware-admission pipeline is used.

## Consequences

- The platform gains controlled email intake without mailbox-wide access.
- Provider credentials and OAuth lifecycle remain outside the current trust boundary.
- Messages cannot silently become authoritative facts or evidence.
- Consent withdrawal can stop ingestion immediately.
- Provider-specific OAuth adapters and scheduled retention jobs require a later operational-security decision.
