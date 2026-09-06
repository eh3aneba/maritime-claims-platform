# ADR-117 — Operator accessibility and recovery states are part of the production boundary

## Status
Accepted as the Phase 14.5 design under #212. The implementation is not part of `main` until its pull request passes the exact-head verification gate and receives fresh explicit merge authorization.

## Context
Phase 12K established bilingual EN/FA presentation, RTL behavior, a mobile navigation drawer, visible keyboard focus and a skip-to-content path. Phase 14 requires a further accessibility/usability polish based on real operator journeys rather than a second broad localization redesign.

Post-Phase-14.4 inspection identified concrete gaps in the authenticated shell:

- the mobile navigation is exposed as an `aria-modal` dialog but Tab and Shift+Tab are not contained inside it;
- the backdrop is implemented as a button and can otherwise become part of keyboard order;
- the secure-session loading state is visual but lacks explicit status/busy semantics;
- the route-level skeleton announces a live region without readable status copy; and
- the route-level error boundary is English-only and lacks an explicit accessible recovery relationship.

These are presentation and interaction defects. They do not require claims-domain changes.

## Decision

### 1. Modal navigation traps keyboard focus
While the mobile navigation dialog is open:

- initial focus moves to the close button;
- Tab from the final focusable control wraps to the first focusable control;
- Shift+Tab from the first focusable control wraps to the last focusable control;
- focus found outside the dialog during a Tab event is returned to the first focusable control;
- Escape closes the dialog and restores focus to the menu button; and
- the click-to-dismiss backdrop is removed from sequential keyboard navigation.

Desktop navigation remains non-modal and is not focus-trapped.

### 2. Loading state must be perceivable without adding side effects
The secure-session loading view exposes `role="status"`, `aria-live="polite"` and `aria-busy="true"` while retaining its existing localized session text.

The route-level skeleton similarly exposes a polite busy status and includes localized screen-reader-only copy. Decorative skeleton blocks are hidden from the accessibility tree.

Loading announcements do not add polling, retries, writes or provider calls.

### 3. Error recovery is bilingual and content-safe
The authenticated route error boundary:

- uses typed EN/FA accessibility copy consistent with the existing modular localization pattern;
- exposes an alert region with explicit heading/description relationships;
- focuses the recovery heading when the boundary renders;
- preserves the existing `reset()` retry action; and
- never renders the supplied exception object, digest, stack trace, request body, claim evidence, credentials or secrets.

The operator-facing statement that claim data has not been changed remains part of the recovery copy.

### 4. Accessibility interactions have zero claim authority
Keyboard navigation, locale switching, loading announcements and route recovery do not create claim, AI, governance or other API writes merely because accessibility behavior is exercised.

The existing real browser acceptance is extended to observe API traffic and fail if accessibility/localization interactions emit non-read HTTP methods after authentication.

## Verification
The Phase 14.5 pull request is merge-ready only when, on the exact pull-request head:

- frontend typecheck/build passes;
- backend full suite passes;
- PostgreSQL migration/preflight passes;
- Docker Compose and dependency-lock checks pass;
- the real localization/accessibility browser journey passes in EN and FA, including forward/reverse focus containment, Escape focus restoration and localized session-loading announcements;
- Operational Performance Smoke passes;
- Production Deployment Policy passes;
- Supply Chain Security passes;
- the branch is not behind `main`;
- there are no unresolved review blockers; and
- fresh explicit user authorization has been given.

## Authority boundary
This decision does not change Claim Facts, Recovery/Time-Bar, Initial Assessment, Correspondence or Claim Pack semantics. It does not add automated coverage, causation, fault, liability, fraud, recoverability, governing-law, legal time-bar effect, reserve, settlement, payment or claim-closure authority. It does not authorize external providers to receive claim evidence.

Refs #212
Refs #202
