# ADR-008: Use a PostgreSQL-backed queue for MVP document processing

## Status
Accepted

## Decision
Persist background document work in `document_processing_jobs` and run a separate worker process. PostgreSQL workers claim jobs with `FOR UPDATE SKIP LOCKED`.

## Rationale
- Durable jobs without adding Redis/Celery/SQS during solo-founder MVP development.
- Processing failures and retry state remain auditable in the same transactional datastore.
- A worker boundary exists from day one and can later be reimplemented behind Celery/SQS without moving claims business logic.

## Constraint
This is an MVP throughput decision, not a claim that PostgreSQL should remain the queue at enterprise scale.
