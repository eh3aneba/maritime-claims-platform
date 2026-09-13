# Phase 17.5-A — Governed external document source profiles

Phase 17.5-A is the configuration-custody foundation for SharePoint and Google Drive integrations.

It creates tenant-scoped, hash-bound source profiles from narrow non-secret provider identifiers, requires Admin + MFA request plus independent Admin + MFA approval, and records the lifecycle in append-only hash-chained receipts.

An `active` profile is **not** a live provider connection. It grants no credential, OAuth, remote-read, synchronization or evidence-admission authority.

## Supported configuration

- SharePoint: `tenant_domain`, `site_id`, `library_id`
- Google Drive: `shared_drive_id`, optional `folder_id`

Unknown configuration fields are rejected fail-closed.

## Safety boundary

This phase performs no OAuth or token exchange, stores no provider credential, makes no provider API call, creates no webhook/subscription or sync checkpoint, reads or mutates no remote file, creates no `Document`, admits no Evidence and mutates no claim.

Future provider connection work must bind to an exact active profile and establish separate authority.
