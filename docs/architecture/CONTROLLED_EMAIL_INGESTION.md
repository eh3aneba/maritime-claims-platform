# Controlled Email Ingestion

The Email Intake Gateway is a provider-neutral boundary for normalized inbound messages. It is intentionally not a mailbox client.

## Consent and credentials

Only a Manager/Admin may create a connection. Creation records the mailbox, provider label, written consent basis and a retention period from 1 to 365 days. A random ingestion token is shown once; only its SHA-256 hash is stored. Connections may be suspended, reactivated or irrevocably revoked.

No Gmail/Outlook OAuth token, password or refresh token is stored in this phase.

## Intake and review

The authenticated webhook accepts bounded normalized metadata and plain text. Provider message IDs are unique per connection. A claim reference such as `MCRI-HM-2026-0001` may create a deterministic suggestion, but never an automatic link.

A user must explicitly link or reject each message with a written reason. Linking creates an inbound Correspondence Centre record and redacts the duplicate staging body.

## Attachments

The webhook accepts attachment manifests only—never bytes. Every manifest is marked `blocked_pending_quarantine`. A future provider adapter must submit bytes through the existing extension, signature, duplicate, quarantine and ClamAV controls before evidence admission.

## Retention

Every staged message receives `retain_until` from the connection policy. A Manager/Admin expiry operation redacts addresses, subject, body and attachment names and writes an audit event. A separately human-filed claim correspondence remains part of the claim record.
