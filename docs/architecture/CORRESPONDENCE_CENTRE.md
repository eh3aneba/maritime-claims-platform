# Correspondence Centre

The Correspondence Centre keeps claim communication drafts and manually filed
external/internal records inside the tenant-scoped claim file.

## Safety boundary

The platform does **not** send email, read a mailbox, synchronize messages or
deliver content to recipients. “Sent Externally” is a manual, audited record of
an action completed outside the platform.

Outbound state flow:

    draft -> under_review -> approved -> sent_externally
                       -> rejected -> draft

- Claims Handlers, Claims Managers and Admins may create and edit drafts.
- Only Claims Managers and Admins may approve or reject wording.
- Marking an approved record “Sent Externally” requires an explicit confirmation,
  channel and optional external reference.
- Approval freezes a SHA-256 hash over direction, kind, sensitivity, parties,
  subject and body. Dispatch is refused if the approved content changes.
- Approved and sent content is immutable; rejected content may return to draft.

Inbound records are manually filed as “received_external”; internal notes are
filed as “filed_internal”. Neither state implies delivery by the platform.

## Sensitivity controls

The data model and UI expose:

- Standard
- Confidential
- Privileged & Confidential
- Without Prejudice

Sensitive headings are inserted into stored content when missing. The label is
a handling aid, not an automated legal determination. Users remain responsible
for jurisdiction-specific privilege and without-prejudice requirements.

## Document-request integration

Creating a rule-driven document-request draft also creates one linked
correspondence record. The existing requirement/task selection remains the
source of truth. Requirement status changes from “missing”/“rejected” to
“requested” only after:

1. the correspondence is submitted;
2. a Manager/Admin approves the exact content; and
3. a user explicitly records external dispatch.

The legacy direct mark-sent endpoint refuses the operation so it cannot bypass
the correspondence review gate.

## Tenancy and audit

Every query is scoped by organization and claim. Audit events cover creation,
editing, submission, approval/rejection and external-dispatch recording. The
audit detail explicitly states that the platform did not send the message.

## Deferred scope

Email ingestion, mailbox connections, automated recipients, retention rules for
provider mailboxes, and actual message sending remain deferred until provider,
consent, security and retention controls are separately designed and approved.
