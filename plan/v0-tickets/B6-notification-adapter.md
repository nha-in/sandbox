# B6 — Notification adapter + Celery send task + delivery log

> **Lane** B — Backend: integrations · **Phase** V0.3
> **Depends on** [B1](B1-integration-ports-http-policy.md) · notification gateway credentials (requested in V0.1)
> **Unblocks** [A4](A4-otp-service.md) real delivery, lifecycle emails for [B7](B7-provisioning-chain.md)/[B8](B8-deprovisioning-chain.md)/[A8](A8-exit-workflow.md)
> **Refs** [06-integrations.md §4](../06-integrations.md) · [03-database.md §3.4](../03-database.md) · [01-backend.md §3.6](../01-backend.md)

## In plain words

Every email the portal sends — OTP codes, "you're approved", "you're rejected", "production approved" — goes through one pipeline: write a log row, send in the background, retry on failure, record the outcome. Staff can always answer "did the integrator get that email?" from the delivery log. One iron rule: **credentials never travel by email** — approval emails link to the portal instead.

## Background

The legacy system sent email/SMS through a resilience-free Feign client, kept delivery records in a **separate notification-DB service**, and emailed integrator credentials in plaintext. v2: one `NotificationGateway` port, always called **from Celery** (never inline in a request), retry with backoff, and a local `notifications_message` delivery log absorbing the separate DB service. Credentials are **never** emailed — approval emails link to the portal's show-once credentials panel ([C7](C7-credentials-panel.md)).

v0 needs these template events: `send-otp`, `sandbox-approved` (link to credentials), `sandbox-rejected`, `exit-sent-back`/`exit-rejected`, `production-approved`.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `notifications` app: `NotificationMessage` model + migration | `sandbox/notifications/models.py` |
| 2 | `enqueue()` service (on-commit scheduling) | `sandbox/notifications/services.py` |
| 3 | `send_notification` Celery task (retry/backoff, terminal FAILED) | `sandbox/notifications/tasks.py` |
| 4 | Real gateway adapter implementing `NotificationGateway` | `sandbox/integrations/notification/adapter.py` |
| 5 | Template-key → gateway-ID mapping in typed settings | `config/settings/*` |
| 6 | Staff delivery-log list (admin or console view) | `admin.py` / console |
| 7 | Tests: on-commit, retry, no-secrets-in-params, per-template params | `sandbox/notifications/tests/` |

### `notifications_message` (delivery log, new `notifications` app)

| Field | Type | Constraints / notes |
|---|---|---|
| `application` | FK → application, null | |
| `user` | FK → user, null | |
| `channel` | char + CHECK | `EMAIL \| SMS` |
| `template_key` | char | see table below |
| `params` | JSONB | render-safe values only — **no secrets, ever** (deny-list check on secret-ish keys) |
| `state` | char + CHECK | `PENDING \| SENT \| FAILED` |
| `attempts` | int | |
| `last_error` | text | |

### v0 template keys

| Key | Fired by | Content notes |
|---|---|---|
| `send-otp` | [A4](A4-otp-service.md) | OTP code |
| `sandbox-approved` | [B7](B7-provisioning-chain.md) completion | **link to the credentials panel — never credentials** |
| `sandbox-rejected` | rejection transition ([B8](B8-deprovisioning-chain.md)) | |
| `exit-rejected` / `exit-sent-back` | [A8](A8-exit-workflow.md) | reviewer comment |
| `production-approved` | [A8](A8-exit-workflow.md) | |

Map keys to gateway template IDs in **typed settings**, re-mapped from the legacy inventory (sandbox-approved/rejected, production-approved, send-otp, exit-sent-back).

### Service + Celery task

```python
# notifications/services.py
def enqueue(*, template_key, recipient, params, application=None) -> NotificationMessage:
    """Writes a PENDING row + schedules the send via transaction.on_commit —
    a rolled-back workflow transition must never send email."""

# notifications/tasks.py
@shared_task
def send_notification(message_id: int) -> None:
    """Idempotent per row (state-guarded re-delivery). Calls the NotificationGateway
    port; retry with exponential backoff (max from settings); terminal failure →
    FAILED + last_error (+ Sentry)."""
```

### Adapter + wiring

- **Adapter** (`integrations/notification/adapter.py`): implements the port against the real gateway — read timeout 5s, errors → `AdapterError("NOTIFICATION", code, retryable)`.
- Wire the workflow side-effects: transitions in [A5](A5-workflow-state-machine.md)/[A8](A8-exit-workflow.md) and chain outcomes in [B7](B7-provisioning-chain.md) call `enqueue(...)`.
- Admin/list view over the delivery log (staff) — v0's delivery visibility.

## Acceptance criteria

- [ ] All v0 template keys mapped + a rendered-params test per template.
- [ ] Enqueue-on-commit proven (rollback ⇒ no row, no task); Celery retry/backoff and terminal FAILED path tested.
- [ ] Contract test against WireMock fixture; timeout (5s) + breaker verified via fault injection.
- [ ] No secret ever appears in params/log (assertion + review); credentials email contains a portal link, not credentials.
- [ ] Offline: fake gateway ([B2](B2-fake-adapters.md)) routes to Mailpit; delivery log rows written identically.

## Out of scope (deferred)

IN_APP channel + notification centre (P5) · SMS unless SANDBOX flow requires it (same port if so) · digest/batching.
