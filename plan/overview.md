# ABDM Sandbox v2 — Proposal Summary

**For:** CTO review · **From:** Platform team · **Date:** 25 Aug 2026 · **Ask:** approval to start build

## Why a rewrite

- Committed to git: production DB passwords, an RSA private key, a signing keystore, a login bypass password
- Developer "local" profile points at the production database
- MD5 password hashing; effectively every API route publicly accessible
- Frontend toolchain end-of-life; test suites don't compile; no CI; no schema migration tooling
- Core logic in 1,400–2,300 line classes with SQL embedded in string constants
- All findings verified line-by-line in a code audit — patching in place costs more than rebuilding
- The git history contains secrets and can never be made public

## Direction

- One Django application serving server-rendered HTML; replaces two codebases (Spring Boot backend + React SPA)
- The product is forms, tables, review queues and dashboards; an SPA adds cost and is the source of today's client-side security problems
- Interactivity via htmx partials; every action still works as a plain form post
- Five enrollment tracks (core sandbox, HCX, NHCX, UHI, HIU) collapse into one application model, one review workflow (approval quorum configurable per environment), one audited state machine
- Ecosystem provisioning becomes idempotent background jobs with a ledger, automatic deprovisioning on rejection/exit, and drift detection — failures are visible and retryable, not silently swallowed

## New capabilities (absent today)

- Conformance service: executable test packs per milestone; a passing run becomes exit evidence, replacing self-declaration
- Hosted reference environment: an ABDM-enabled Care HMIS instance as test counterparty; same stack runs locally with one docker command
- Agent Skills: versioned, installable packs for integrators' own coding tools
- In-portal support desk with response SLAs (today: email threads and an external site)
- Guided "next action" tracker targeting a ten-working-day sandbox journey

## Stack and tooling

- Python 3.14 / Django 6 · htmx + Tailwind (no JS framework) · Postgres 16 · Redis · Celery
- Auth: django-allauth with mandatory MFA for staff; Keycloak scoped to integrator machine credentials only
- Engineering: uv, ruff, mypy, pytest, Playwright
- CI: GitHub Actions with gitleaks (secret scanning) and Trivy (image/dependency scanning) as merge gates
- Runtime: Docker behind Traefik; Sentry, OpenTelemetry, Prometheus
- Local development fully offline: docker compose + seeded demo data, no VPN

## Kept and dropped

- Kept (ecosystem dependencies): Keycloak, WSO2 API Manager, HIE-CM gateway, notification gateway
- Dropped: Strapi and Meilisearch — content and search move into the application; one-time content import at cutover, then both decommissioned
- Dropped: Kafka — the audit topic has no consumer and its events carry no usable data; replaced by an append-only audit table covering every workflow transition
- New repository — the old history cannot be scrubbed safely

## Delivery

- Six phases: foundation/CI → domain + enrollment → workflow + reviews → integrations + provisioning → reporting/content/support → hardening
- Written exit criteria per phase; every screen ships with an authorization test
- Pen test and a 10,000-application load test before launch
- The two large additions (conformance, assistant) are feature-flagged and cannot block launch

## Decisions needed

1. v1 data: migrate existing applications or re-enroll integrators — needed before phase 5
2. AI assistant hosting: managed API or self-hosted model, given government data constraints — feature-flagged, can ship without it
