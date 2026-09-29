# Phase 17.6-AE-B — SFTP operator readiness and baseline observability

AE-B extends the existing External Evidence operations page.

## Profile card

For SFTP profiles the operator sees:
- overall SFTP runtime readiness;
- credential qualification status/time;
- host-key transport verification status/time;
- SFTP session activation status/time.

A green runtime state requires a coherent current qualification chain, not merely three successful historical rows.

## Evidence family row

For SFTP N+1+, the page additionally shows whether the recurring baseline is established or a transition is required.

Transition required is included in the operator attention filter.

## Governed action

If an exact AC admission exists and current N+1 still needs a recurring baseline, the page exposes the explicit AD establish-baseline action.

It remains a separate human-authorized API call.

## Read-only overview

Refreshing the overview never contacts SFTP and never resolves a credential.

All mutation authority remains in dedicated governed APIs.
