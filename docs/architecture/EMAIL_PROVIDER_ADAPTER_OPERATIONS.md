# Email Provider Adapter Operations

Provider adapters are deployment workers around the controlled normalized-email gateway. The application stores only a provider kind, one allowlisted folder, canonical read-only capabilities and a reference such as `vault://...`; OAuth access and refresh tokens remain in the deployment secret system.

An adapter cannot be active unless its consented ingestion connection is active. Allowed capabilities are limited to `messages.read.allowed_folder` and `attachments.metadata.read`. Send, reply, forward, delete, archive and mailbox-wide application permissions are rejected.

Every run is bounded to 100 messages or less and uses an adapter-scoped idempotency key. Raw provider cursors are not persisted; only a SHA-256 checkpoint is retained. The run ledger records trigger, counts, status and a bounded failure summary.

Retention execution is tenant-scoped and idempotent. It invokes the existing audited staging-redaction policy and records a separate operational run. Provider delivery still uses the normalized authenticated gateway, where deduplication, human claim linking and attachment-manifest blocking already apply.
