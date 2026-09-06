# Phase 15.8 exit gates

Before squash merge, the exact PR head must pass:
- backend full test suite;
- Alembic migration chain and PostgreSQL application preflight;
- frontend typecheck and production build;
- Docker validation;
- MT ORION browser journey;
- Operational Performance Smoke;
- Production Deployment Policy;
- Supply Chain Security;
- main-to-branch comparison with `behind_by=0`;
- no unresolved blocking review threads;
- fresh explicit user authorization for squash merge.

Any new commit resets these gates for the new exact head.
