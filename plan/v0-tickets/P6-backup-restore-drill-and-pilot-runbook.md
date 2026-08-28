# P6 — Backup/restore drill + pilot runbook

> **Lane** P — Platform · **Phase** V0.4 Milestones, exit & pilot readiness
> **Depends on** staging live (V0.1), seeded data ([A9](A9-seed-sandbox-demo.md)), full journey working ([C9](C9-playwright-e2e.md))
> **Unblocks** pilot go/no-go review
> **Refs** [07-infra-cicd.md](../07-infra-cicd.md) · [00-master-plan.md §6](../00-master-plan.md)

## In plain words

Before real integrators use the pilot, we prove we can recover from disaster — by actually restoring a backup, not by claiming we could — and we write the operator's handbook: how to deploy, roll back, fix a stuck provisioning job, and who to call. This ticket produces a rehearsed procedure and a document, not product code.

## Background

ABDM Sandbox v2 is a server-rendered Django monolith replacing the legacy Spring Boot + React portal. The v0 pilot takes a handful of invited integrators end-to-end on the new stack while the legacy portal stays live for everyone else. Before the pilot starts, we must prove we can recover the system and hand operators a written guide. The legacy system had no CI, no runbooks and manual dated ALTER scripts — recovery was never rehearsed; that must not carry over.

This is the last Platform ticket: an executed drill plus a document, not new product code.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Scheduled Postgres + uploads-bucket backups on staging, retention documented | platform config |
| 2 | Executed restore drill + write-up (steps, observed RPO/RTO, gaps + fixes) | `docs/runbooks/restore-drill.md` |
| 3 | Pilot runbook (contents below) | `docs/runbooks/pilot.md` |
| 4 | One rehearsed image rollback on staging | pipeline evidence in the write-up |

### Details

1. **Automated backups**
   - Nightly Postgres backups for staging (and the production environment when it exists): platform snapshots or `pg_dump`, retention documented.
   - Uploads bucket (declaration documents): versioning/replication enabled.
   - Secret-store inventory documented (names/ARNs only — never values): Django `SECRET_KEY`, DB/Redis creds, Keycloak service account, WSO2 admin, notification gateway key.
2. **Restore drill — executed, not just written**
   - Restore the latest staging backup into a scratch environment.
   - Run `manage.py migrate --check`, then a smoke checklist: login, view a seeded application, perform one mutation, check Sentry receives events.
   - Record observed RPO/RTO, every manual step, and gaps found; fix the gaps and re-run until clean.
3. **Pilot runbook** (in-repo, `docs/`)
   - Deploy + rollback: previous image + reversible-migrations policy (additive-first, two-step column drops).
   - Provisioning failure triage: reading the `integrations_provisioned_resource` ledger, console retry button, when to escalate ([B7](B7-provisioning-chain.md)).
   - Credential paths: integrator self-service rotation vs rotating **our** service accounts (Keycloak/WSO2/notification gateway).
   - Revocation latency note: integrator access is JWT-based, so deprovisioning takes effect at token expiry (sandbox token lifetime ≤15m — see [B8](B8-deprovisioning-chain.md)).
   - Sentry triage basics; backup/restore procedure (from the drill); staging data refresh via `seed_sandbox_demo`.
   - Pilot constraints: invite-only, docs link out to the legacy site, legacy portal untouched.
   - Escalation contacts.

## Acceptance criteria

- [ ] Backups run on schedule; restore drill executed and written up (steps, timings, gaps + fixes).
- [ ] Restored instance passes the smoke checklist.
- [ ] Rollback (previous image) rehearsed once on staging.
- [ ] Runbook reviewed by the team and merged; referenced from the go/no-go checklist.

## Out of scope (deferred to main plan)

Production HA/DR design · load testing (P6) · OTel/Prometheus dashboards (P4/P6) · pen test (required before public GA, not the pilot).
