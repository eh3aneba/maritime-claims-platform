# Phase 17.6-AD — SFTP N+1 release and recurring baseline transition

Phase AD governs what happens after AC creates canonical Evidence version N+1.

## Fresh processing release

N+1 starts without downstream-processing authority.

The generic release endpoint must be used again for that exact new Document version.

A release attached to the prior version does not transfer.

## Explicit recurring baseline

AC does not silently move the recurring observation baseline.

An Admin with current MFA establishes a separate immutable transition after verifying:
- AC admission;
- AB refresh;
- originating changed observation;
- active recurring schedule;
- current family binding and exact N+1 Document.

The transition records the refreshed projection/version token as the trusted baseline.

## Zero-I/O transition

Establishing the transition performs no:
- SFTP stat/content/list;
- storage read/write;
- Document mutation;
- schedule mutation;
- checkpoint mutation;
- processing enqueue;
- AI execution.

## Next due tick

Until the transition exists, N+1 recurring observation fails closed.

After the transition, a due tick that sees the same refreshed metadata is `unchanged`.

## Next

Phase AE will close the full production SFTP integration and operator acceptance loop.
