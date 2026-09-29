# SFTP production runtime runbook

## Feature flags

Production SFTP networking is disabled by default.

Enable only after SFTP profiles and credential references have been configured through the governed product workflow:

`EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED=true`

Supported live secret backends are configured as a comma-separated allow-list:

`EXTERNAL_EVIDENCE_SFTP_SECRET_BACKENDS=azure_key_vault,gcp_secret_manager`

Unsupported configured backends cause startup failure.

## Credential secret format

### Password

```json
{
  "username": "claims-reader",
  "authentication_kind": "password",
  "password": "<secret>"
}
```

### Private key

```json
{
  "username": "claims-reader",
  "authentication_kind": "private_key",
  "private_key": "<PEM-or-OpenSSH-private-key>",
  "passphrase": "<optional-secret>"
}
```

Do not store these values in MCRI configuration, logs or database fields. Only store the governed secret reference.

## Host key

The source profile uses a pinned OpenSSH SHA256 fingerprint.

A host-key change must be treated as an authority change. Do not simply replace the fingerprint after a failed connection. Re-qualify the endpoint through the governed SFTP transport/credential flow.

## Destination policy

The production runtime rejects private, loopback, link-local, multicast, reserved and unspecified resolved destinations unless the governing request explicitly permits private destinations.

Current Phase 17.6 requests are fail-closed for private destinations.

## Read behavior

Directory discovery uses one bounded non-recursive listing.

Exact metadata observation uses `lstat`, not `stat`, so symbolic links are not followed.

Exact content read performs:
1. path-within-root validation;
2. one `lstat` no-follow preflight;
3. rejection unless the entry is a regular file;
4. one bounded read;
5. immediate handle/session/transport closure.

## Incident signals

Treat these as operator-visible failures:
- host-key mismatch;
- DNS/destination-policy rejection;
- secret reference unavailable;
- authentication failure;
- SFTP subsystem activation failure;
- path-policy violation;
- symlink rejection;
- read/list/stat timeout;
- content byte-bound violation.

Never include raw password, private key, passphrase, secret value or file content in incident logs.

## Rotation

Credential rotation should update the external secret version/reference through the governed credential-reference workflow and then re-run health/session qualification.

Host-key rotation requires explicit endpoint re-qualification.

## Rollback

Disable:

`EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED=false`

This prevents live SFTP adapter registration on restart. It does not delete profiles, Evidence, checkpoints, schedules or audit history.
