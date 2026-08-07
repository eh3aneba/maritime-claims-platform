# Rule-driven tasks and document request workflow

Sprint 4 Phase B turns active missing-document rules into controlled actions without introducing autonomous outbound communication.

## Models

- `claim_tasks`: tenant-scoped work items with type, priority, source, assignee, due date and completion evidence.
- `document_request_batches`: immutable-ish correspondence-draft checkpoints containing subject, reusable draft body, selected requirement IDs, recipient label and due date.

## Core flow

1. Rules Engine evaluates the claim.
2. Claim Handler selects missing requirements or chooses **Request all Critical**.
3. Platform creates/reuses one open `document_request` task per requirement and creates a new correspondence draft batch.
4. Requirement remains `missing` until the user confirms the request was actually sent externally.
5. User marks the batch as requested/sent; selected requirements become `requested`.
6. A matching document upload refreshes Rules Engine state to `received`.
7. The open document-request task auto-completes, preserving completion reason and audit events.

## Safety boundary

The platform does not send email in this phase. Draft text is deterministic and editable/copyable. No LLM is required to decide which documents to request. Future LLM copy-polishing may be added behind human approval without changing the requirement state machine.

## Audit actions

- `CREATE_DOCUMENT_REQUEST`
- `MARK_DOCUMENT_REQUEST_SENT`
- `COMPLETE_CLAIM_TASK`
- `AUTO_COMPLETE_DOCUMENT_TASK`
