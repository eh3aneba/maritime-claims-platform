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

The runtime restricts SSH host-key negotiation to the strong algorithm allow-list already enforced by the governed transport-verification contract. Weak `ssh-rsa` negotiation is rejected before authentication.

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
5. **exact byte-count verification**: the received total must equal the verified opened-handle regular-file `st_size`. A partial read followed by an apparent EOF is rejected with `read_failed`, and no partial Evidence bytes are returned; a real zero-byte file remains valid;
6. immediate handle/session/transport closure.

## Operational telemetry

Live SFTP operations emit metadata-minimal JSON events through the `mcri.sftp.operation` logger.

Allowed fields are limited to:
- operation;
- outcome;
- normalized failure code;
- duration_ms.

Never add hostname, address, path, username, credential reference, fingerprint, secret material or content to this logger.

Operational counts and latency summaries should be derived from these structured events in the deployment log pipeline.

## Controlled real-TCP failure acceptance (Pilot #652)

The opt-in real-OpenSSH acceptance suite also exercises two **real loopback socket** failures using the production `LiveSftpRuntime.probe_host_key` operation, independently of the OpenSSH server: a peer that accepts the TCP connection and closes without sending an SSH banner, and a peer that accepts but withholds the SSH banner until the client's bounded handshake fails. Both must fail closed **before authentication or an SFTP session** and must never be interpreted as an accepted host-key probe. The test peer is a disposable socket bound to `127.0.0.1` on a kernel-assigned port, never a customer server or credential backend; no secret/file/remote path is sent.

An additional **actual authenticated OpenSSH read-interruption scenario** establishes a real SFTP session, verifies the opened file, reads its first genuine chunk, then deliberately closes only that client's transport before the next read. The expected fail-closed result is `read_failed`, with `content=None`, `content_read_count=0` and no remote write. It is a **client-injected post-auth transport teardown**, not a server-initiated network outage, so no real customer endpoint is touched. A separate deterministic unit regression forces **short data followed by apparent EOF**, proving the new exact-length safeguard rejects truncated files even without a socket exception. Full OpenSSH server-side mid-session fault and complete canonical v1→N+1 production acceptance remain separate controlled tests/NO-GO conditions.

These scenarios complement the existing controlled actual OpenSSH checks (wrong host pin, failed authentication, missing files, symlink/traversal, oversize and permissions). They prove real transport refusal/handshake behavior against a test socket, **not** in-session disconnect or large-file read timeout against the actual OpenSSH subsystem. A successful CI run must be tied to its exact PR SHA and named SFTP workflow; an optional SFTP test being skipped by generic CI is not evidence of live-server acceptance. End-to-end real initial-v1→N+1 governance, real production scanner/durable store and accountable operator acceptance remain separate NO-GO criteria in #652/#656.

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
