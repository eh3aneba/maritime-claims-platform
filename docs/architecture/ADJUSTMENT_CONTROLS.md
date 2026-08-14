# Advanced Financial Adjustment Controls

The Adjustment Workspace turns current human-reviewed invoice cost items into a
versioned adjustment statement. It supports professional claim adjustment without
automating policy interpretation, recoverability, settlement or payment.

## Source boundary

- A new statement snapshots invoice line items in one currency.
- Quotation alternatives are never included in cumulative claimed totals.
- No FX conversion is performed.
- Each line retains its Cost Item, source Document and AI Run identifiers plus a
  frozen source snapshot.
- Later source changes do not mutate an approved version.

## Human adjustment decisions

Every line must receive an explicit treatment:

- Included
- Excluded
- Apportioned
- Credit

and an explicit adjustment basis:

- Particular Average (PA)
- General Average (GA)
- Sue & Labour
- Running Down Clause (RDC)
- Other
- Not applicable

Pending/unallocated lines block submission. Exclusions, apportionments, credits
and differences from the claimed amount require a written reason.

Statement-level deductible and other deduction/credit amounts require a written
basis. The application performs deterministic arithmetic only:

    net adjusted = gross considered - deductible - other deduction/credit

The current reserve is displayed for comparison and is never updated automatically.

## Review lifecycle

    draft -> under_review -> approved
                         -> rejected -> draft

Claims Handlers may prepare and submit. Only Claims Managers and Admins may
approve or reject. Approved versions are immutable and receive a SHA-256 content
hash over totals, controls, source manifest and all line decisions.

The approved adjusted total is a human-reviewed calculation record. It is not an
automated coverage conclusion, settlement offer, payment instruction or payment
authorization.

## Versioning and audit

Each claim has monotonically increasing statement versions. A new version
snapshots the then-current invoice schedule. Audit events cover creation, line and
statement edits, submission, approval and rejection.

All reads and writes are scoped by organization and claim.
