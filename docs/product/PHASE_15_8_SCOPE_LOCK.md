# Phase 15.8 scope lock

This tranche is limited to provider credential-reference metadata minimization, explicit rotation lifecycle, shared resolver semantics, and related regression coverage.

Out of scope:
- real Vault or cloud Secret Manager client integration;
- OAuth refresh-token lifecycle;
- provider send/modify/delete authority;
- automatic claim linking or Correspondence promotion;
- automatic Evidence admission or document processing;
- substantive claim decisions;
- operator-facing provider administration UI.

Any of these requires a separately bounded design/issue after Phase 15.8.
