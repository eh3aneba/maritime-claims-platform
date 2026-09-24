# ADR-243: Qualify SFTP credential-reference health without opening SFTP authority

## Status

Accepted for Phase 17.6-C implementation.

## Context

Phase 17.6-A governs one read-only SFTP source profile with normalized connection identity and a pinned host-key fingerprint. Phase 17.6-B governs one approved, non-secret external secret-manager reference for future SFTP authentication material.

The next safe authority increase is to determine whether that approved reference can be resolved and whether the resolved material class matches the approved authentication kind. That proof is useful before any SSH/SFTP connection authority exists, but it must not silently become a remote-login or file-access capability.

## Decision

Phase 17.6-C introduces one credential-health qualification per active Phase 17.6-B binding.

A registered resolver may internally resolve the approved external secret reference. The resolver contract returns only bounded metadata:

- whether resolution succeeded;
- the resolved material class: `password` or `private_key`; and
- one bounded failure code when qualification fails.

Raw password, private-key or passphrase bytes never cross the resolver boundary into the service contract.

## One-use qualification

Each Phase 17.6-B binding may have at most one health qualification.

Exact replay returns the existing qualification without a second secret-resolution attempt. Materially changed replay conflicts.

The exact binding row is locked before qualification so concurrent consumers cannot multiply resolution authority.

## Qualification result

A result is:

- `qualified` when the reference resolves and its material kind exactly matches the approved `authentication_kind`; or
- `unqualified` with a bounded failure code.

An otherwise resolvable reference with the wrong material kind is recorded as `authentication_kind_mismatch`.

Unexpected resolver exceptions are converted to the bounded `resolver_rejected` result so internal exception details do not leak and the attempt remains auditable.

## Integrity

The qualification hash lineage binds:

- organization/profile identity;
- exact Phase 17.6-A profile hash;
- exact Phase 17.6-B binding ID;
- binding scope, request and approval hashes;
- exact locator hash;
- expected authentication kind;
- reference backend;
- resolver kind;
- request facts; and
- bounded result facts.

Requested and completed receipts form an append-only hash chain.

## Safety boundary

The qualification records that secret resolution was attempted, but all other capability facts remain false.

Phase 17.6-C does not:

- persist credential bytes;
- return credential bytes from APIs;
- log credential bytes;
- authenticate to SSH/SFTP;
- open an SSH/SFTP socket or session;
- list, stat, read, write, rename or delete remote files;
- create remote checkpoints;
- stage remote content;
- admit Evidence;
- create Documents;
- enqueue processing;
- execute AI; or
- mutate Claims.

## Consequences

The platform gains proof that the approved external credential reference is structurally suitable for future SFTP authentication, while remote connectivity authority remains absent.

A later Phase 17.6-D may separately authorize a bounded SSH/SFTP connection and pinned-host-key handshake. File listing and content reads remain later, separately reviewed authority increases.

## Verification

Release requires:

- active exact 17.6-B custody;
- tenant isolation;
- exact replay without a second resolver call;
- changed replay conflict;
- qualified and unqualified outcomes;
- authentication-kind mismatch rejection;
- bounded resolver failures;
- receipt and upstream-lineage tamper detection;
- zero secret persistence in DB/API/audit;
- zero SSH/SFTP/file/Evidence/processing/AI/Claim authority.

References: Issue #537, Phase 17.6-A and Phase 17.6-B.
