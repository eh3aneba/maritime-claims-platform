# Phase 15.8 frontend contract note

The backend provider adapter/run response contract no longer emits raw `credential_reference` or raw `checkpoint_hash`; it emits bounded lifecycle metadata and `checkpoint_present` instead.

The current web application has no operator-facing Email Provider page or runtime consumer of those legacy response fields. Existing frontend helper/type declarations therefore do not create a runtime disclosure path in this tranche, and frontend typecheck/build remains the validation gate.

When the operator-facing provider administration UI is introduced, its dedicated types must be generated or updated from the safe backend contract before the UI is enabled. That follow-up must not reintroduce secret locators or checkpoint fingerprints to the browser response surface.
