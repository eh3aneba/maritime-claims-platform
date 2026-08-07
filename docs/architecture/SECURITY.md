# Security foundation

This document is a living checklist, not a security certification.

## Sprint 2 requirements

- Environment variables for secrets
- Password hashing when authentication is introduced
- Backend tenant isolation
- CORS restricted by environment
- File hash on upload
- Audit log for sensitive operations
- No sensitive document contents in application logs
- HTTPS required in staging/production
- Soft-delete and traceability rules for claim records

## Before first external pilot

- Threat model
- Dependency scanning
- Secret scanning
- Backup/restore test
- Access-control tests
- File malware scanning strategy
- Penetration test
- Data-processing agreement templates
