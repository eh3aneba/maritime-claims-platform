# Phase 17.5-H — Bounded provider-client activation execution

## Goal
Consume one exact, unexpired Phase 17.5-G provider-client activation authorization into one local activation execution record without increasing provider authority.

## Admission chain
Phase H requires the exact integrity-valid lineage through:
- Phase 17.5-A source profile;
- Phase 17.5-B discovery;
- Phase 17.5-C connection authorization;
- Phase 17.5-D bootstrap execution;
- Phase 17.5-E credential-reference binding;
- Phase 17.5-F `resolvable` health qualification; and
- Phase 17.5-G `authorized` provider-client activation authorization.

The G authorization must be unexpired, `execution_limit=1`, tenant-scoped and unconsumed. The H operator must be Admin + MFA.

## Lifecycle
H execution lifecycle is exactly:
- `requested → completed`.

At completion:
- `activation_authorization_consumed=true`;
- the Phase G authorization is atomically terminalized and its live authorization flag is cleared;
- the Phase G terminal reason names the exact H execution ID; and
- H stores the resulting G terminal hash.

Phase G uses its existing terminal `expired` status for both unused expiry and consumed closure. The reason/hash prove which occurred: a consumed G authorization has the Phase H execution-specific terminal reason, while a naturally expired unused authorization has the unused-expiry reason.

## Replay and concurrency
- one H execution per Phase G authorization;
- exact replay returns the same completed H execution;
- changed replay conflicts;
- a second request key cannot consume the same G authorization;
- the G row is locked before first consumption and H rechecks after lock acquisition, preventing two concurrent consumers from both winning.

## Stored facts
H stores only non-secret lineage and governance facts:
- G authorization ID, scope/request/authorization hashes and original expiry;
- F qualification ID and health hashes;
- E binding ID and lineage hashes;
- provider kind, reference backend, resolver kind and locator hash;
- H request key, requester, reason and timestamps;
- H scope/request/completion hashes;
- the G terminal hash created at consumption; and
- append-only H receipt hashes.

No locator namespace/name/version or resolved secret value is stored by H.

## API
- `POST /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-authorizations/{authorization_id}/activation-executions`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{execution_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/provider-client-activation-executions/{execution_id}/receipts`

All endpoints require Admin + MFA. Request schemas forbid additional fields, so secret/token-like material such as `client_secret` cannot be smuggled into the Phase H request body.

## Safety boundary
The sole new positive execution fact is:
- `activation_authorization_consumed=true` on completed H execution/receipt state.

H keeps false:
- `credential_reference_resolution_performed`;
- `credential_stored`;
- `oauth_authorization_code_stored`;
- `oauth_token_exchanged`;
- `access_token_stored`;
- `refresh_token_stored`;
- `client_secret_stored`;
- `private_key_stored`;
- `provider_client_activation_authorized`;
- `provider_network_performed`;
- `remote_list_performed`;
- `remote_read_performed`;
- `remote_write_performed`;
- `remote_delete_performed`;
- `subscription_created`;
- `checkpoint_created`;
- `sync_executed`;
- `evidence_admitted`;
- `document_created`; and
- `claim_mutated`.

`credential_reference_stored=true` on H means only that the execution is lineage-bound to the already-governed non-secret Phase E credential-reference metadata. H stores no secret value and does not resolve the reference.

## Fail-closed behavior
- pending, rejected or otherwise non-authorized G: 409;
- naturally expired G: terminalize/audit expiry and return 409;
- cross-tenant authorization/execution access: 404;
- changed replay or second consumption: 409;
- upstream E/F/G integrity or activity invalidation: 409;
- H receipt tamper/truncation: 409;
- H lineage/hash drift: 409.

## Acceptance coverage
The consolidated H acceptance test uses one database reset and covers:
- real A→B→C→D→E→F→G→H lineage;
- pending G denial;
- legitimate rejected G denial in a rollback transaction;
- legitimate expired G denial in a rollback transaction;
- explicit rejection of secret-like extra request fields;
- tenant isolation;
- successful one-time G consumption;
- immediate terminalization of consumed G;
- exact replay and changed replay conflict;
- second-consumption rejection;
- requested/completed H receipt chain;
- receipt truncation rejection in a rollback transaction;
- receipt tamper rejection;
- upstream credential-binding disable causing completed H reads to fail closed;
- unchanged Claim and Document counts; and
- all OAuth/token/provider-network/remote-document/Evidence/Document/claim flags remaining false.

## Next boundary
A separately reviewed later phase may introduce a narrowly bounded provider-client construction or credential-resolution execution step. Any real secret-manager resolution, OAuth/token acquisition, Microsoft Graph/SharePoint/Google Drive network call, remote file list/read, synchronization, Document creation or Evidence admission must remain an explicit, separately reviewed authority increase.

See ADR-212 and issue #416.
