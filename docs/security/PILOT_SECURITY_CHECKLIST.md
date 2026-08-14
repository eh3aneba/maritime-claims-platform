# Private Pilot Security Checklist

## Required before sharing with a design partner

- [ ] `SECRET_KEY` replaced with 32+ random characters.
- [ ] Database password replaced; no `change-me-*` value remains.
- [ ] `.env` is not committed to Git.
- [ ] `CORS_ALLOWED_ORIGINS` contains only expected web origins.
- [ ] External AI remains disabled unless contractual/data-processing approval exists.
- [ ] `ALLOW_EXTERNAL_AI_RESTRICTED=false` unless separately approved.
- [ ] Pilot host is private/VPN-restricted or bound to an approved internal network.
- [ ] TLS is used before any staging/production internet exposure.
- [ ] Evidence storage directory/volume is access-controlled and backed up.
- [ ] `MALWARE_SCAN_ENABLED=true`; ClamAV health passes before the API accepts pilot traffic.
- [ ] ClamAV port `3310` remains internal to the Compose network and is not internet/host published.
- [ ] Clean synthetic upload and isolated EICAR rejection have both been verified.
- [ ] A database backup is taken before upgrading or restoring pilot data.
- [ ] Demo credentials are changed from examples and shared out-of-band.
- [ ] Only synthetic data is used until data-processing terms and retention rules are agreed.

## Current MVP limitations

- Local object storage is suitable for a private single-host pilot, not high availability.
- ClamAV admission scanning covers new uploads only; evidence marked `legacy_unscanned` still needs a controlled rescan workflow.
- Quarantined bytes require an operator-defined retention, investigation and secure purge procedure.
- No SSO/SAML, session revocation list or enterprise identity lifecycle yet.
- No formal penetration test has been completed.
- No production-grade secrets manager integration yet.
- Backup automation is baseline/manual; retention and off-host encryption must be configured by the operator.

These limitations are acceptable only for a controlled design-partner pilot using synthetic or formally approved data. They are not a claim of production certification.
