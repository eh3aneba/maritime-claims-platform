# Phase 17.5-AG — Human review decision boundary

## Purpose
Convert a pending Phase 17.5-AF review handoff into one explicit human decision without performing external I/O.

## Decision matrix
| AF result | Human decision | Downstream refresh authorization |
| --- | --- | --- |
| changed | approve_refresh | yes, narrow and unconsumed |
| changed | dismiss | no |
| missing | acknowledge_missing | no |
| missing | dismiss | no |

## Human authority
Admin role + current MFA. The human reviewer is persisted as the real local `users.id`; no service identity may stand in for the reviewer.

## Freshness checks
Before a decision, AG revalidates organization, Claim, profile, family binding, provider/source identity and the canonical current Document lineage against the AF handoff. Historical AF data is never rewritten.

## Hard boundaries
No provider client, token, remote list/read/write/delete, storage access, Document mutation, Evidence admission, processing, AI, Claim mutation, or checkpoint advancement.

## Next phase
A later phase may consume an approved changed-item refresh authorization to perform one narrow exact-item content-refresh workflow. That execution must revalidate authority again and remains separate from AG.
