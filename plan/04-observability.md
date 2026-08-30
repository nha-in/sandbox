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

### Not built yet — correlation is declared, not wired

`utils/correlation.py` and B1's `traceparent`/`X-Correlation-Id` headers exist, and
`audit_event.correlation_id` is stamped by `emit()`. Nothing else is done, and until
it is, the id joins nothing:

- **No request binding.** `set_correlation_id()` is called nowhere outside tests.
  There is no middleware.
- **Nothing is structured.** django-structlog is not a dependency, and both
  `base.py` and `production.py` format with
  `"%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"`.
  A `%`-formatter renders only `%(message)s`, so the `extra={...}` dict that
  [B1](v0-tickets/B1-integration-ports-http-policy.md)'s `IntegrationClient._log`
  attaches to every outbound call — system, op, status, duration, outcome,
  correlation id — is **dropped on the floor**. Every adapter call currently logs
  the bare string `integration call`. Installing a JSON formatter is what turns
  that line from decoration into data, and it is a settings change, not a code one.
- **The id can bleed between requests.** `get_correlation_id()` generates on first
  use into a `ContextVar`, which under sync Django is per-*thread* and outlives the
  request. A second request on the same worker thread inherits the first one's id
  rather than getting its own. Worse than a missing id, because it looks valid.
- **It dies at the Celery boundary.** Nothing puts the id on the task message and
  nothing rebinds it in the worker, so a task mints a fresh one. Every log line an
  adapter writes from a worker — the whole of [B7](v0-tickets/B7-provisioning-chain.md)'s
  chain and [B6](v0-tickets/B6-notification-adapter.md)'s sends — would be
  unjoinable to the request that caused it even once the fields survive.

What this costs concretely: a `notifications_message` row settles `FAILED` after
five attempts and `last_error` holds the last one. What attempts 1–4 did is
currently unrecoverable — not merely hard to find — because the fields were never
emitted and recipients are deliberately not logged.

The fix is one ticket, not per-lane work: JSON formatter, bind on the request,
propagate on the task message, rebind in the worker, then persist the id on the
rows that need joining back to it (`notifications_message`,
[B1](v0-tickets/B1-integration-ports-http-policy.md)'s ledger). Those columns are
deliberately **not** added ahead of the wiring — a column nobody writes
meaningfully invites people to trust it.

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
