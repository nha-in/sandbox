# A4 — OTP service (Redis token bucket, attempt caps)

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review
> **Depends on** V0.1 (Redis, Mailpit) · notification delivery via [B6](B6-notification-adapter.md) fake/console email until V0.3 lands
> **Unblocks** [C4](C4-enrollment-wizard.md) (OTP verify step)
> **Refs** [01-backend.md §3.3](../01-backend.md) · [05-security.md §3.2](../05-security.md) · [03-database.md](../03-database.md)

## In plain words

Before an application goes to reviewers, the applicant proves they control their contact address by typing a 6-digit code we send them. This ticket is the engine behind that: generate the code, check it safely, and strictly limit how often codes can be requested or guessed (so nobody can brute-force or spam it). The screen that uses this engine is built separately in [C4](C4-enrollment-wizard.md).

## Background

The enrollment flow requires the applicant to prove they control the contact details before the application can be submitted. Verification belongs to the **contact**, not the application: it stamps `users_user.email_verified_at` / `phone_verified_at`, and submit is guarded on both being set — it is not a workflow state. Legacy did the same thing (`/send-otp` takes an email address and nothing else) but with no principled rate limiting and a captcha bolted on; v2 replaces that with a Redis token bucket and attempt caps — **no captcha carry-over**.

This is a pure backend service consumed by the wizard's OTP partial ([C4](C4-enrollment-wizard.md)); email delivery goes through the notification port (fake adapter prints to console/Mailpit until [B6](B6-notification-adapter.md) ships the real one).

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `issue_otp` / `verify_otp` services | `sandbox/applications/services/otp.py` |
| 2 | Redis token-bucket rate limiting, limits in settings | same + `config/settings/base.py` |
| 3 | `OTP_RATE_LIMITED` / `OTP_EXPIRED` / `OTP_INVALID` DomainErrors | shared error module |
| 4 | Audit events for issue / verify-success / verify-fail | via [A5](A5-workflow-state-machine.md) helper (shim until it lands) |
| 5 | Unit tests: limits, expiry, single-use, re-issue invalidation | `sandbox/applications/tests/` |

### Service API

```python
# applications/services/otp.py (or module of similar shape)
def issue_otp(identity: str) -> None:
    """6-digit code, TTL ~5 min. Re-issue invalidates the previous code.
    Stored in Redis HASHED — never plaintext at rest, never logged."""

def verify_otp(identity: str, code: str) -> None:
    """Constant-time compare; single-use. On success marks the identity
    verified for the pending application. Raises DomainError on failure."""
```

### Rate limits (Redis token bucket, settings-driven)

| Limit | Dimension | Suggested default |
|---|---|---|
| issue rate | per identity | 3 / 10 min |
| verify attempts | per code | 5, then the code is invalidated |
| issue + verify | per IP | broader bucket — blunts enumeration |

Carry the legacy numeric limits where they exist.

### Error contract (never a 500)

| `DomainError` code | Raised when | The view renders |
|---|---|---|
| `OTP_RATE_LIMITED` | bucket empty | form error + cooldown hint |
| `OTP_EXPIRED` | TTL passed | form error + resend option |
| `OTP_INVALID` | wrong code | form error (attempts remaining decremented) |

### Wiring

- Sends via the `NotificationGateway` port (template key `send-otp`) — service code never imports an adapter directly.
- Audit: issue/verify-success/verify-fail emit audit events (via [A5](A5-workflow-state-machine.md)'s audit helper once it lands; keep a small shim until then).

## Acceptance criteria

- [ ] Unit tests (fake Redis or test instance): happy path, expiry, wrong-code cap → invalidation, issue-rate cap, re-issue invalidates prior code, single-use enforced.
- [ ] Constant-time comparison verified in code review; codes never logged or stored un-hashed.
- [ ] Works offline: `compose up` → OTP email visible in Mailpit via the fake notification adapter.
- [ ] mypy/ruff clean.

## Out of scope (deferred)

SMS OTP (email-only in v0 unless the SANDBOX flow strictly requires SMS — then it goes through the same port) · captcha (dropped by design).
