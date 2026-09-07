# ADR-128: Claim Domain Context Consumption in Claims Intelligence

## Status
Accepted for Phase 16.1-B.

## Context
Phase 16.1-A introduced a separate, append-only `ClaimDomainClassification` lineage so product/workflow `ClaimType` is not overloaded with marine casualty context. The existing Claims Intelligence stack already consumes controlled Claim Facts, chronology, document requirements, rule issues, financial data, policy intelligence and structured Recovery/Time-bar evaluations.

The next requirement is to make the current human-confirmed domain classification visible in Claims Intelligence without turning classification into a trigger, rule input or substantive claim decision.

## Decision
### 1. Consumption happens only during an explicit Claims Intelligence build
Creating or superseding `ClaimDomainClassification` does not invoke Claims Intelligence. The current classification is read only when an authenticated operator calls the existing explicit Intelligence build path.

### 2. Current classification is source context, not rule input
Phase 16.1-B does not pass the incident category, component or failure mode into `evaluate_claim_rules`. The existing deterministic rule layer runs exactly as before.

The Intelligence base source hash is extended with a bounded representation of the current classification:
- classification id;
- catalog version;
- classification number;
- incident code;
- optional component code;
- optional failure mode;
- classification integrity hash.

The free-text classification note is not copied into the Intelligence source state or rendered item. Its content remains indirectly integrity-bound because it is part of the classification hash produced by Phase 16.1-A.

### 3. Render one non-actionable domain-context item
When a current classification exists, Claims Intelligence renders exactly one `domain_context` item using canonical catalog labels. The item:
- is informational severity;
- has evidence value 100 because it comes from a human-confirmed canonical record;
- has no action type;
- has no suggested action;
- links to the exact classification id/hash/catalog version;
- explicitly states that it is not a causation, coverage, fault, liability, recoverability or other substantive conclusion.

### 4. Reclassification changes the next content-addressed snapshot
Because the current classification identity/hash participates in source-state hashing, a later human reclassification produces a different Intelligence source identity on the next explicit build. It does not create a snapshot at classification time.

### 5. Preserve established engine-version contract
The persisted Claims Intelligence `engine_version` remains the established core contract version `12A.1`. Existing Phase 12C Recovery/Time-bar integration remains independently versioned. Phase 16.1-B adds its own integration version `16.1-B.1` to the summary and snapshot/source hashes rather than silently changing the established contract field.

## Authority boundary
Domain-context consumption does not automatically:
- create or alter Claim Facts;
- create document requirements or tasks;
- execute additional or classification-specific rules;
- create an Intelligence snapshot when classification is recorded;
- determine or imply coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or closure.

Any future use of classification to select rules, evidence requirements, similar claims or AI prompts requires a separately governed phase with explicit source/version lineage and regression tests.

## Consequences
### Positive
- Claims Intelligence can show a stable, human-confirmed marine casualty context;
- reclassification is reflected deterministically without mutating old snapshots;
- sensitive free-text classification notes are not propagated into intelligence output;
- the rule and substantive-decision authority boundaries remain unchanged;
- existing consumers that rely on `engine_version=12A.1` remain compatible.

### Trade-offs
- classification does not yet tailor the rule set or evidence matrix;
- only the current classification is rendered, while full historical lineage remains available through the dedicated classification-history API;
- domain-context presentation remains intentionally non-actionable until a later governed tranche defines downstream authority.
