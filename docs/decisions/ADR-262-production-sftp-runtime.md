# ADR-262: Production SFTP runtime behind governed adapter contracts

## Status

Proposed for Phase 17.6-AE-A.

## Context

Phases 17.6-A through AD establish governed SFTP authority, custody, Evidence, recurring observation, refresh and versioning boundaries.

The remaining production-runtime gap is network execution. Test adapters prove contracts but do not create a production SFTP client.

## Decision

Use Paramiko 5.0.0 as the pinned production SSH/SFTP client and register it only behind a separate disabled-by-default feature flag.

The live runtime reuses the existing SFTP adapter contracts and does not create new authority.

## Startup

`external_evidence_live_sftp_adapters_enabled=false` by default.

When enabled:
- Paramiko must import successfully;
- configured secret backends must be supported;
- invalid configuration fails application startup.

When disabled, Paramiko is not imported by runtime registration and no SFTP network action occurs.

## Secret references

Initial live secret backends:
- Azure Key Vault;
- Google Secret Manager.

Credential payloads are transient JSON.

Password authentication:
- `username`;
- `authentication_kind: password`;
- `password`.

Private-key authentication:
- `username`;
- `authentication_kind: private_key`;
- `private_key`;
- optional `passphrase`.

Username in the secret must match the governed profile username for list/stat/read operations.

No secret/private-key/password is persisted or returned.

## Network boundary

Each operation:
1. applies destination/DNS policy;
2. opens one TCP connection;
3. completes SSH handshake;
4. verifies OpenSSH SHA256 host-key fingerprint;
5. resolves credential material only for authenticated operations;
6. authenticates once;
7. opens one SFTP subsystem;
8. performs only the requested bounded operation;
9. closes SFTP, transport and socket immediately.

No shell or exec channel is allowed.

## No-follow file reads

The historical content-read contract prohibited any remote stat while also requiring `follow_symlinks=false`.

That combination cannot honestly enforce no-follow semantics with standard SFTP.

AE-A therefore permits a truthful exact `lstat` preflight before the one content read. Historical proof rows with `remote_stat_performed=false` remain valid. New production reads may persist `remote_stat_performed=true`.

Paramiko documents `lstat` as retrieving metadata without following symbolic links.

## Read-only operations

Allowed:
- directory listing;
- exact lstat;
- exact file read.

Disallowed:
- write;
- rename;
- delete;
- mkdir/rmdir;
- chmod/chown;
- touch;
- shell/command execution.

## Operational observability

Live SFTP adapter wrappers emit one content-free structured event per bounded operation.

The event contains only:
- event name;
- operation class;
- succeeded/failed outcome;
- normalized failure code when present;
- elapsed milliseconds.

It never contains hostname, IP, remote path, username, credential locator, host-key fingerprint, secret/private-key/passphrase, file metadata or file content. Runtime exception text is not logged.

Counts and latency distributions are derived from the deployment log pipeline, consistent with the existing Phase-14 observability baseline rather than introducing a second in-process metrics authority.

## Supply chain

Paramiko is exact-pinned and must appear in the generated hash-locked production requirements.

AE-A is not mergeable until dependency-lock consistency, dependency audit/SBOM, image scan and all normal production gates pass.

## Follow-up

AE-B: operator UX and observability.

AE-C: restart/replay/recovery and full production-shaped v1→N+1 acceptance.
