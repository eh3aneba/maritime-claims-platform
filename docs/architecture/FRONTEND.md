# Frontend Architecture — Sprint 2 Phase F

The MVP frontend is a Next.js/TypeScript application that communicates with the FastAPI API from the browser using credentialed requests. Authentication remains authoritative in the API; the UI only reflects the authenticated session.

## Routes

- `/login` — organization-aware login
- `/dashboard` — organization claim summary
- `/claims` — searchable/filterable claim portfolio
- `/claims/new` — H&M machinery claim creation and minimal vessel creation
- `/claims/[id]` — claim overview, workflow status, reserve control, and secure evidence upload/list/download/remove UI

## Security boundaries

- The frontend never talks directly to PostgreSQL.
- The browser includes the API's HttpOnly authentication cookie using `credentials: include`.
- Route protection in the UI is a usability measure only; API tenant and role enforcement remains authoritative.
- Cross-tenant IDs returned or manipulated in the browser cannot bypass backend tenant filters.

## Design principles

- Workflow-first rather than chatbot-first.
- Evidence and exception surfaces take priority over decorative analytics.
- Conservative enterprise styling suitable for insurers, ship managers and P&I workflows.
- Responsive web for MVP; no native mobile application.

## Current limitation

Secure document handling is active in Phase G. AI-derived classification, extraction, chronology and evidence reasoning remain intentionally deferred to Sprint 3.
