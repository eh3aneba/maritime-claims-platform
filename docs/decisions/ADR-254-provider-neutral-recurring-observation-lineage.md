# ADR-254: Provider-neutral recurring-observation lineage contract

## Status

Proposed for Phase 17.6-W.

## Context

Evidence-family binding and downstream processing release are now provider-neutral for SFTP, but recurring observation still embeds SharePoint/Google Drive lineage directly in due-tick execution.

The legacy due-tick row stores mandatory generation-3 observation/checkpoint foreign keys and the service loads legacy admission and provider metadata structures directly. This blocks SFTP convergence and would encourage a duplicated scheduling stack.

## Decision

Introduce a provider-neutral recurring-lineage resolver with provider-specific bounded adapters behind one normalized contract.

The resolver returns:

- provider kind and profile hash;
- durable stable source identity;
- exactly one provider-specific observation/checkpoint selector pair;
- observation operation identity;
- current provider policy hash;
- a bounded exact-item metadata read context.

Legacy SharePoint/Google Drive resolution preserves its existing admission → generation-3 observation/checkpoint lineage and exact-item metadata adapter.

SFTP resolution starts at the provider-neutral U family binding and revalidates the T → S → R → Q → P lineage. It derives source identity only from the trusted profile and relative-path hash and uses the existing exact-file SFTP stat adapter.

## Persistence

Due-tick observation execution keeps the historical legacy lineage columns, makes them nullable, and adds nullable SFTP R/Q lineage columns.

A provider-aware XOR constraint requires exactly one complete lineage pair.

Legacy hashes retain the old `provider_lineage_observation_id` scope key. New SFTP rows use a separate `sftp_provider_lineage_observation_id` key so historical hashes are not reinterpreted.

Due-tick dispatch persistence is widened to allow `sftp`, but SFTP schedule authorization remains explicitly closed during W.

## SFTP metadata boundary

The SFTP recurring reader:

- performs one exact-file stat;
- does not list directories;
- does not read file content;
- does not read/write object storage;
- does not persist credential/session/raw path material;
- normalizes unchanged/changed/missing into the generic due-tick result shape.

The raw path exists only transiently inside the already-governed SFTP request object.

## Authority staging

W prepares lineage and execution infrastructure only.

Recurring schedule authorization for an SFTP family still fails closed with an explicit Phase-X boundary error. Phase X is the first authority-opening step for SFTP recurring schedules.

## Compatibility

Existing SharePoint/Google Drive schedules and due-tick hashes must remain valid and their tests remain unchanged.
