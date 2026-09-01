# Claims Intelligence Engine

## Purpose

Phase 12A turns the platform's existing evidence, chronology, deterministic rules, policy intelligence and financial controls into one source-linked claim-level decision-support view for H&M machinery claims.

The engine is deliberately not a chatbot and does not introduce a new external-provider scope. It composes already-controlled records and human-reviewed evidence into a versioned intelligence snapshot.

## Source layers

A snapshot may consume only tenant-scoped platform records, including:

- current claim record;
- human-approved `ClaimFact` records and their document/extraction/segment lineage;
- current document versions;
- active deterministic document requirements and rule-generated claim issues;
- chronology events and unresolved evidence conflicts built from human-reviewed extractions;
- reviewed policy/contract terms and issue spots;
- reviewed financial cost items and open financial flags.

The build refreshes the deterministic rules and chronology layers first. It does not cause a new provider call and does not expand the Sprint 11T provider authorization.

## Immutable snapshot model

`claim_intelligence_snapshots` is versioned per claim and content-addressed by `source_state_hash`. Rebuilding against an identical controlled source state returns the existing snapshot. A material source-state change creates the next immutable snapshot version.

Each `claim_intelligence_item` stores:

- category and stable item key;
- title and explanatory description;
- severity, urgency, evidential value and ranking score;
- explicit rationale for why the item was surfaced;
- structured source references;
- optional handler action;
- item SHA-256.

Item categories include incident summary, chronology, machinery context, evidence available, missing evidence, conflict, hypothesis, issue flag, financial lead, recovery lead, deadline lead and next action.

## Human review ledger

Snapshots and items are not edited in place. Handler actions are appended to `claim_intelligence_item_decisions` as `accept`, `edit` or `dismiss` records with a chained decision hash.

An accepted or edited suggestion may be explicitly converted into a controlled `ClaimTask` with source `ai_suggestion`. Task creation does not turn the candidate into an authoritative claim fact or decision.

## Marine-specific issue spotting

The first release includes explainable non-authoritative leads for:

- missing H&M machinery evidence;
- chronology and evidence conflicts;
- maintenance/running-hours/recent-overhaul hypotheses already surfaced by the rules engine;
- policy wording and notice/time-limit review flags;
- financial-control flags;
- candidate AAA D1 / D2 / D6 cost-review prompts;
- emergency expense classification review across PA repair cost, Sue & Labour, salvage and General Average;
- potential third-party/workmanship recovery preservation.

The engine does not decide that any clause, adjusting rule or recovery theory applies. These are human-review prompts only.

## Security and governance

Every query is tenant scoped. Material intelligence carries source references and immutable hashes. The engine never silently rewrites approved facts, chronology resolutions, policy terms, financial decisions or assessment snapshots.

The following remain prohibited:

- autonomous coverage or liability conclusions;
- autonomous causation findings;
- automated reserve, settlement or payment decisions;
- automated recovery responsibility findings;
- unrestricted external-provider processing;
- authoritative claim-fact updates from intelligence candidates.

## Product workflow

A handler opens the claim Intelligence workspace, builds or refreshes a snapshot, inspects ranked source-linked items, opens lineage, and explicitly accepts, edits, dismisses or converts a recommended action into a controlled task. Historical snapshots and decision hashes remain available for audit and later evaluation.
