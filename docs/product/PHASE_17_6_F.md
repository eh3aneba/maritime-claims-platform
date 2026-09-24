# Phase 17.6-F — bounded SSH transport and pinned host-key verification

## Goal

Perform the first live SFTP-path network proof while stopping before SSH user authentication or SFTP subsystem activation.

## Current preparation

The first implementation slice is deliberately network-free:

- define the destination-policy contract;
- bind exact approved hostname and port;
- validate a supplied resolved-address set;
- default-deny private/internal destinations;
- always deny loopback, link-local, unspecified, multicast and reserved addresses;
- fail closed if any address in a multi-address resolution violates policy.

## Why policy comes first

The platform must not create a socket before it knows the destination is permitted.

Keeping destination validation pure also makes SSRF and DNS-rebinding rules independently testable.

## Future live adapter boundary

A later commit in this phase may introduce one registered bounded adapter that may:

- resolve the approved hostname once;
- validate all resolved addresses;
- open one short-lived TCP/SSH transport;
- perform only enough SSH negotiation to obtain the server host key;
- compare the exact pinned OpenSSH SHA256 fingerprint;
- close immediately.

It must not authenticate a user or start SFTP.

## Result model

Only bounded metadata should survive the call, for example:

- result status: `verified` / `unverified`;
- bounded failure code;
- host-key algorithm class;
- latency class;
- destination policy hash.

Raw socket objects, transport handles and reusable sessions must never be returned or persisted.

## Safety boundary

No credential resolution, SSH user authentication, SFTP session, remote command, directory listing, file read/write/delete, Evidence, Document, processing, AI or Claim mutation.

## Next boundary

17.6-G may separately authorize and execute bounded SSH user authentication + SFTP subsystem activation only after one exact successful F verification.

See Issue #542 and ADR-246.
