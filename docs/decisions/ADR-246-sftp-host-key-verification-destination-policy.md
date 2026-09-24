# ADR-246: Bound SFTP SSH transport destination before any live handshake

## Status

Accepted for Phase 17.6-F implementation planning.

## Context

Phase 17.6-E consumes one approved SFTP handshake authorization locally and still performs no network I/O.

Phase 17.6-F is the first planned authority increase that may contact the configured SSH/SFTP endpoint. Before any socket exists, destination policy must fail closed against SSRF-style retargeting and internal-network access.

## Decision

Separate destination policy from network execution.

A pure policy layer validates:

- exact approved normalized hostname;
- exact approved port;
- resolved IP addresses supplied by a later bounded adapter;
- no empty resolution result;
- no unspecified, loopback, link-local, multicast or reserved destination;
- private/internal destinations denied by default;
- every resolved address must satisfy policy, not merely one address.

The policy module performs no DNS lookup and opens no socket.

## Private-network policy

Private/internal IP ranges are denied by default.

A future deployment may only allow private networks through an explicitly reviewed deployment-level policy input. This must never be controlled by the remote source profile or ordinary request payload.

Even when private networks are explicitly allowed, loopback, link-local, unspecified, multicast and reserved destinations remain denied.

## Host binding

The future network adapter must receive the exact approved hostname and port already bound into the A→E lineage.

The adapter may not silently substitute an alternate hostname, redirect target, fallback port or proxy-selected destination.

## DNS rebinding boundary

All addresses returned by one bounded DNS resolution must pass policy before a connection attempt.

If any resolved address violates policy, the whole attempt fails closed.

The later network implementation should connect only to an address from that already validated result set and should not perform an untracked second resolution.

## Safety boundary

This ADR does not authorize:

- DNS resolution by the policy module;
- TCP sockets;
- SSH version exchange;
- SSH key exchange;
- user authentication;
- SFTP subsystem activation;
- remote commands;
- remote file operations.

## Next implementation increment

The remaining 17.6-F implementation may add a bounded adapter that:

1. receives the exact approved destination;
2. resolves once;
3. applies this destination policy;
4. opens one transient transport;
5. obtains the server host key;
6. compares its OpenSSH SHA256 fingerprint with the exact pinned fingerprint;
7. closes the transport;
8. returns only bounded result metadata.

Authentication and SFTP subsystem activation remain out of scope.

References: Issue #542, ADR-245.
