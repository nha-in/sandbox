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

| #   | Deliverable                                                        | Where                                          |
| --- | ------------------------------------------------------------------ | ---------------------------------------------- |
| 1   | `notifications` app: `NotificationMessage` model + migration       | `sandbox/notifications/models.py`              |
| 2   | `enqueue()` service (on-commit scheduling)                         | `sandbox/notifications/services.py`            |
| 3   | `send_notification` Celery task (retry/backoff, terminal FAILED)   | `sandbox/notifications/tasks.py`               |
| 4   | Real gateway adapter implementing `NotificationGateway`            | `sandbox/integrations/notification/adapter.py` |
| 5   | Template-key → gateway-ID mapping in typed settings                | `config/settings/*`                            |
| 6   | Staff delivery-log list (admin or console view)                    | `admin.py` / console                           |
| 7   | Tests: on-commit, retry, no-secrets-in-params, per-template params | `sandbox/notifications/tests/`                 |

### `notifications_message` (delivery log, new `notifications` app)

| Field          | Type                   | Constraints / notes                                                                 |
| -------------- | ---------------------- | ----------------------------------------------------------------------------------- |
| `application`  | FK → application, null |                                                                                     |
| `user`         | FK → user, null        |                                                                                     |
| `channel`      | char + CHECK           | `EMAIL \| SMS`                                                                      |
| `template_key` | char                   | see table below                                                                     |
| `params`       | JSONB                  | render-safe values only — **no secrets, ever** (deny-list check on secret-ish keys) |
| `state`        | char + CHECK           | `PENDING \| SENT \| FAILED`                                                         |
| `attempts`     | int                    |                                                                                     |
| `last_error`   | text                   |                                                                                     |

### v0 template keys

| Key                                | Fired by                                                | Content notes                                         |
| ---------------------------------- | ------------------------------------------------------- | ----------------------------------------------------- |
| `send-otp`                         | [A4](A4-otp-service.md)                                 | OTP code                                              |
| `sandbox-approved`                 | [B7](B7-provisioning-chain.md) completion               | **link to the credentials panel — never credentials** |
| `sandbox-rejected`                 | rejection transition ([B8](B8-deprovisioning-chain.md)) |                                                       |
| `exit-rejected` / `exit-sent-back` | [A8](A8-exit-workflow.md)                               | reviewer comment                                      |
| `production-approved`              | [A8](A8-exit-workflow.md)                               |                                                       |

Map keys to gateway template IDs in **typed settings**, re-mapped from the legacy inventory (sandbox-approved/rejected, production-approved, send-otp, exit-sent-back).

### Service + Celery task

```python
# notifications/services.py
def enqueue(
    *, template_key, recipient, params, application=None
) -> NotificationMessage:
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

- [x] All v0 template keys mapped + a rendered-params test per template (parametrised over all six; asserts every param reaches the body and no `{{` survives).
- [x] Enqueue-on-commit proven (rollback ⇒ no row, no task); Celery retry/backoff and terminal FAILED path tested.
- [ ] Contract test against WireMock fixture; timeout (5s) + breaker verified via fault injection — **partly done**. Timeout, breaker, and the 4xx-off-the-breaker rule are asserted against a recording stub transport; the WireMock suite itself is [B9](B9-wiremock-fault-injection-suite.md).
- [x] No secret ever appears in params/log (deny-list, asserted, applied recursively); the approval email carries a portal link, not credentials.
- [x] Offline: fake gateway ([B2](B2-fake-adapters.md)) routes to Mailpit; delivery log rows written identically.
- [ ] Verified end-to-end against the real notification service — **blocked on NHA**: we have no template ids for our tenant, and no SMS provider endpoint.

### Decisions worth knowing

- **The model is `Message`, not `NotificationMessage`.** The table is specified as
  `notifications_message` ([03-database.md §3.4](../03-database.md)), which is the
  default for `Message` in the `notifications` app; and
  `ports.NotificationMessage` already means the DTO crossing the port.
- **`send-otp` is logged but not queued.** The log records that a code went to an
  address and whether it landed; `params` stays empty, because the only param is
  the live code. Legacy stored the *rendered* body, so `notification_audit` still
  holds every OTP it ever sent. The code cannot simply be moved off the row
  either: `CELERY_RESULT_EXTENDED` puts task kwargs in the Redis result backend
  and `CELERY_TASK_SEND_SENT_EVENT` broadcasts them to any monitor, and parking
  the plaintext in the OTP cache would defeat the HMAC digest that is there so a
  stolen cache is not brute-forceable. So `otp.service` calls
  `notifications.send_now()` — inline, logged, no retry. Retry buys little here:
  the code expires in `OTP_TTL_SECONDS`, a delayed attempt would deliver a dead
  one, and resend already mints a fresh code.
- **The notification-DB service is gone.** Legacy fetched every template *body*
  at send time from a second service and substituted `var1` locally. Bodies are
  Django templates here; only the gateway template id still travels.
- **HTTP-level retry is off for the send.** A retried POST is a second email, so
  `IntegrationClient` gets one attempt and `send_notification` owns retry — it
  can see, from the row, whether the previous attempt settled.
- **`credentials_url` was renamed `panel_url`.** The params deny-list matches
  `credential` as a substring; a params name that has to be argued about is worth
  changing instead.

## Out of scope (deferred)

IN_APP channel + notification centre (P5) · digest/batching.

**SMS is in scope.** The deferral used to read "SMS unless SANDBOX flow requires
it" — it does: [A4](A4-otp-service.md) and [C4](C4-enrollment-wizard.md) both
block submit until `email_verified_at` **and** `phone_verified_at` are set, and
OTP is the only way a phone gets verified. `NotificationMessage` carries a
`channel` (`EMAIL|SMS`) and the fake records SMS sends; **this ticket owes the
real SMS adapter**, which needs an ABDM SMS provider endpoint.
