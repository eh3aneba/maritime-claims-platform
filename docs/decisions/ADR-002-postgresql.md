# ADR-002: Use PostgreSQL as the primary datastore

Status: Accepted

## Decision
Use PostgreSQL for structured application data and later add pgvector for semantic search.

## Rationale
Marine claim data is strongly relational: claims connect to vessels, documents, events, costs, reserves, tasks, and decisions.
