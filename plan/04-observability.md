# 04 — Observability

**Parent:** [00-master-plan.md](00-master-plan.md) · **Audience:** backend/platform engineers

---

## 1. In plain words

When something goes wrong — a provisioning step fails at 2am, an email never arrives — we need to see it, find the exact request that caused it, and follow it through every system it touched. That means: structured logs (machine-readable, searchable), one **correlation id** that travels from the browser request through Celery tasks into every external call, error reporting (Sentry) that pages a human, and health endpoints the load balancer can trust. v0 keeps it deliberately small (logs + Sentry); v1 adds metrics, traces and alerting.

## 2. Legacy findings

Unstructured logs; `REQUEST-ID` handled ad-hoc with correlation dying at every Feign/Kafka boundary; no metrics or traces; the Kafka audit topic was producer-only and content-free (object hashes). Audit "observability" that observed nothing — v2 drops Kafka entirely for the append-only `audit_event` table ([00-master-plan.md](00-master-plan.md) §4).

## 3. Design

- **Logs:** structlog JSON; request id + user/org + correlation id bound per request (django-structlog); Celery task logs carry the same correlation id; htmx fragment requests distinguishable via `HX-Request`/`HX-Target`.
- **Errors:** Sentry for Django + Celery, release-tagged (wired in V0.1).
- **Health:** `/healthz` (process up) and `/readyz` (DB `SELECT 1`, Redis ping, broker reachable — 500ms budgets). External systems are **excluded from readiness** — a Keycloak/WSO2 outage must not evict the portal from the load balancer; they surface via adapter logs/metrics instead.
- **No browser telemetry stack** — the server renders HTML, so Sentry sees view/template errors natively.

## 4. v0 (POC)

Sentry + structured logs + health endpoints only — enough to run the pilot responsibly:

- structlog JSON with correlation id across request → Celery → adapter call (`traceparent`/correlation headers already required by [B1](v0-tickets/B1-integration-ports-http-policy.md)).
- Per-adapter-call structured log line (system, op, duration, outcome — never secrets).
- Sentry alerts on: provisioning chain terminal failures, notification terminal failures, unhandled view/task errors.
- `/healthz` + `/readyz`.

**Exit criteria:** one correlation id demonstrably traverses request → chain → external call in staging logs; `PROVISIONING_FAILED` produces a Sentry event.

## 5. v1 — everything else

| Item | Phase |
|---|---|
| OpenTelemetry auto-instrumentation (Django, psycopg, httpx, Celery, Redis); 100% error / 10% baseline sampling | P4/P6 |
| django-prometheus + celery-exporter + postgres/redis exporters; breaker state as a metric; `/metrics` internal-only | P4/P6 |
| Page-level SLOs: p95 TTFB per URL group (public/integrator/console) at Traefik + middleware | P6 |
| Full alert set: reconciliation `ORPHANED`, breaker-open per system, queue depth/age, `/readyz` flaps, error rate per URL group, SLA breaches, conformance runner errors, callback probes `UNREACHABLE` | P4–P6 |
| Dashboards: golden signals per URL group, adapter health, chain outcomes, queue health | P6 |

## 6. Definition of done

**v0**

- [ ] Correlation id end-to-end verified by an integration test.
- [ ] Sentry receives and groups chain/notification terminal failures; on-call knows where to look ([P6 runbook](v0-tickets/P6-backup-restore-drill-and-pilot-runbook.md)).

**v1**

- [ ] Metrics/traces live; alert runbooks exist for every alert (linked from the alert itself).
