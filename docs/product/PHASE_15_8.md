# Phase 15.8 — provider credential lifecycle

Phase 15.8 removes raw provider credential locators and checkpoint fingerprints from normal API/audit surfaces and adds explicit, tenant-scoped credential-reference rotation.

Implemented controls:
- raw `credential_reference` remains internal to persistence/runtime and is not serialized in normal adapter responses;
- raw `checkpoint_hash` remains internal and is represented only by `checkpoint_present` in normal adapter/run responses;
- adapter creation/rotation audit records exclude old/new locators, resolved bearer values, raw checkpoints, checkpoint hashes, and operator reason text;
- credential-reference rotation is Admin/Claims Manager only, tenant-scoped, explicit-confirmation gated, blocked for revoked adapters and while a checkpoint handoff is pending;
- rotation preserves the acknowledged provider cursor and canonical claim state and does not call Graph/Gmail or a secret store;
- `env://` resolution occurs only at execution time from the process environment;
- `vault://` and `secret-manager://` remain explicit fail-closed backends until real clients/configuration are implemented;
- Graph/Gmail execution and provider attachment acquisition continue through the shared credential resolver contract;
- legacy malformed references are classified only as `invalid` in safe metadata and can be repaired by explicit rotation without reflecting the locator.

Authority remains unchanged: no send/modify/delete provider authority, no automatic claim link or Correspondence promotion, no automatic Evidence admission/processing, and no substantive claim decision authority.
