# ADR-123: Gmail recurring synchronization uses governed history cursors, not message-list page tokens

- **Status:** Accepted
- **Date:** 2026-09-06
- **Phase:** 15.6
- **Parent:** #214

## Context

Phase 15.2 introduced bounded Gmail read-only execution and treated the opaque value returned by `messages.list.nextPageToken` as the next external checkpoint. That value is suitable for continuing one paginated message-list result set, but it is not Gmail's incremental mailbox synchronization cursor.

Gmail incremental synchronization is based on mailbox history ids and `users.history.list(startHistoryId=...)`. Gmail also specifies that a stale or invalid history id may return HTTP 404, in which case a full synchronization is required.

The application already keeps raw provider checkpoints outside the database and stores only SHA-256 checkpoint hashes. That security boundary remains correct; the semantic meaning of the Gmail checkpoint must now be corrected without weakening source, staging, Evidence or human-review authority.

## Decision

### 1. Gmail checkpoints are versioned opaque application envelopes

The public execution contract remains unchanged: the operator/external orchestrator receives an opaque `next_checkpoint` string and must return it on the next execution.

For Gmail, the opaque value now uses a strict versioned envelope with three modes:

- `bootstrap_page`: initial full snapshot pagination; contains the original baseline mailbox history id plus the next Gmail `messages.list` page token;
- `history`: steady-state incremental cursor; contains the last accepted Gmail history id;
- `history_page`: continuation of a paged `users.history.list` result; contains the original `startHistoryId` plus the history page token.

The envelope is validated strictly for version, mode, history-id shape and bounded page-token/checkpoint length.

A pre-15.6 unversioned Gmail page token is not guessed or reinterpreted. It fails with fixed code `gmail_checkpoint_resync_required` and requires explicit operator reset.

Raw checkpoint envelopes remain external. The application database and audit log continue to store only hashes/presence metadata, never raw checkpoint values.

### 2. Initial bootstrap captures history before snapshot pagination

When a Gmail adapter has no expected checkpoint, the execution path first reads the mailbox profile and captures its current `historyId`.

Only after that baseline is captured does it perform a label-scoped `messages.list` snapshot.

If the snapshot has additional pages, each returned `bootstrap_page` checkpoint preserves the same original baseline history id. When the final snapshot page completes, the next checkpoint becomes a steady `history` checkpoint using that original baseline.

This ordering allows the subsequent history execution to retrieve changes that happened while bootstrap pagination was in progress rather than advancing immediately to a later cursor and silently skipping those changes.

### 3. Recurring execution uses `users.history.list`

A steady `history` checkpoint invokes Gmail History with:

- `startHistoryId` from the external checkpoint;
- the configured adapter label id;
- `historyTypes=messageAdded`;
- the bounded adapter result limit.

Only message ids explicitly present in `messagesAdded` are fetched as full messages. Duplicate ids in the same history response are deduplicated before staging.

If the response has another history page, a `history_page` checkpoint preserves the original start history id and page token. When history pagination completes, the steady cursor advances to the response `historyId`.

If one bounded history response expands to more unique message ids than the configured adapter batch limit, execution fails closed with `gmail_history_batch_overflow` rather than silently skipping ids while advancing the cursor.

### 4. Stale history does not automatically reset synchronization authority

A Gmail History HTTP 404 maps to fixed failure code `gmail_history_resync_required`.

That failure records a normal governed failed provider run and bounded retry/reconciliation metadata, but it does **not** clear the stored checkpoint hash automatically.

Likewise, an unversioned legacy checkpoint produces `gmail_checkpoint_resync_required` without automatic mutation of checkpoint authority.

This prevents a provider response or malformed external cursor from silently forcing a full mailbox bootstrap.

### 5. Full resync requires a separate human reset action

A manager or administrator may invoke the Gmail checkpoint-reset endpoint only when:

- the adapter is Gmail;
- the adapter belongs to the caller's tenant;
- the adapter and consented connection are active;
- the latest run failed with exactly `gmail_history_resync_required` or `gmail_checkpoint_resync_required`;
- the caller explicitly confirms reset;
- a checkpoint hash is still present.

The reset clears only the stored checkpoint hash and makes the adapter due for a fresh bootstrap. It does not delete or mutate previously staged messages, Correspondence, attachment quarantine state, canonical Evidence or claim records.

Repeated reset after the hash has already been cleared fails closed rather than creating duplicate authority events.

### 6. Reconciliation remains content-free

Manager reconciliation may expose:

- last fixed run failure code;
- whether checkpoint reset is currently available;
- operational state;
- checkpoint presence/handoff requirement already represented by existing bounded fields.

It must not expose raw checkpoint envelopes, provider page tokens/history ids, credential references/values, mailbox content, attachment content or claim evidence.

After an eligible human reset, the adapter is shown as `due` for a fresh bootstrap even though the previous run remains a historical failed run.

### 7. Graph behavior is unchanged

Microsoft Graph continues to use validated folder-scoped delta links. This decision does not modify Graph checkpoint semantics, credential authority, attachment-byte authority or scheduling authority.

## Consequences

### Positive

- Gmail recurring pulls now use the provider's intended incremental history model.
- Bootstrap changes are recoverable because the baseline history id is captured before snapshot pagination.
- Legacy page tokens cannot be silently mistaken for incremental cursors.
- Stale history cannot trigger autonomous full resynchronization.
- Operators have a bounded, explicit and auditable resync action.
- Raw checkpoint custody remains outside the application database.

### Trade-offs

- Existing Gmail adapters with a pre-15.6 stored checkpoint hash may require one explicit reset after their next legacy checkpoint attempt is rejected.
- External orchestrators must continue to retain the opaque checkpoint value between runs.
- Large Gmail history records that exceed the configured message batch fail closed and require operational intervention rather than silently truncating mailbox changes.

## Non-authority statement

This decision grants no Gmail send, modify, delete, trash, read-state or label-write authority; no automatic claim association; no automatic Correspondence promotion; no attachment-byte acquisition or Evidence admission authority; no automatic document processing; and no authority over coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure.
