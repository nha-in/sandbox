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

| #   | Deliverable                                                     | Where                            |
| --- | --------------------------------------------------------------- | -------------------------------- |
| 1   | `send_otp` / `verify_otp` + storage, TTL, attempt cap           | `sandbox/otp/`                   |
| 2   | `request_otp` / `verify_otp` services, stamping the user        | `sandbox/users/services.py`      |
| 3   | Issue rate limiting on the cache API, limits in settings        | same + `config/settings/base.py` |
| 4   | `OTP_RATE_LIMITED` / `OTP_EXPIRED` / `OTP_INVALID` DomainErrors | `sandbox/utils/errors.py`        |
| 5   | Unit tests: limits, expiry, single-use, re-issue invalidation   | `sandbox/users/tests/`           |

OTP verification belongs to the **contact**, so the calling service lives in
`users`, not `applications` — `applications/services.py` owns draft writes and
is unrelated code. Audit events for issue/verify moved to
[A5](A5-workflow-state-machine.md), which owns the audit helper.

### Service API

Code generation, expiry and attempt counting live in **`sandbox/otp/`**, a
standalone module that knows nothing about users, organisations or applications
and works on an opaque `identity` string. It is ours to maintain — **not** an
external system like Keycloak, so it is not a port and not in `ExternalSystem`.
The module boundary is what keeps it swappable.

Legacy did the same: `generateSecureOTP()` + `OTPRedisHash` in the sandbox's own
Redis. Only _delivery_ was remote, via `NotificationFClient` to ABDM's global
notification gateway — which is our `NotificationGateway` port.

The flow is transaction-based, matching legacy: issue returns a
`transaction_id`, verify takes it back. Legacy carried these as
`emailTransactioId` / `mobileTransactioId` on the enrollment.

```python
# sandbox/otp/
def send_otp(identity: str, channel: NotificationChannel) -> OtpChallenge: ...
def verify_otp(challenge: str, identity: str, code: str) -> OtpVerification: ...

# users/services.py
def request_otp(*, user: User, identity: str) -> str:
    """Rate-limited; returns the transaction id the wizard holds onto.
    Refuses an identity the user does not own, so it cannot be used to mail
    codes to arbitrary addresses."""

def verify_otp(*, user: User, identity: str, challenge: str, code: str) -> None:
    """On success stamps email_verified_at / phone_verified_at.
    Raises DomainError on failure."""
```

The code never leaves the module — `send_otp` mails it and returns only the
transaction id. Stored as an HMAC keyed on `SECRET_KEY`: **legacy kept the OTP
in plaintext in Redis and string-compared it**
(`decryptedOtp.equals(otpDetails.getOtp())`) — v2 does not.

### Rate limits (cache-backed, settings-driven)

Carried from legacy `OtpServiceImpl` + `SandboxConstant` — the implementation
that handles **both** SMS and email, and the authoritative one:

| Limit           | Dimension     | Value                             | Provenance                                                                                                |
| --------------- | ------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------- |
| resend cooldown | per identity  | **90 s**                          | `RESEND_COOLDOWN_SECONDS = 90000` — milliseconds despite the name, compared against `currentTimeMillis()` |
| issue rate      | per identity  | **5 per 10 min**                  | `MAX_RESEND_ATTEMPTS = 5`, counted over live codes (which live for the TTL)                               |
| verify attempts | per challenge | **5**, then the code is destroyed | `MAX_WRONG_ATTEMPTS = 5`                                                                                  |
| code TTL        | per challenge | **10 min**                        | `OTP_VALIDITY_MINUTES = 10`                                                                               |

`seconds_until_resend(identity)` backs C4's visible cooldown without having to
trigger the error first.

Re-issuing invalidates every earlier code for that identity (legacy sets
`expired = true` on each previous `Otp`).

A second, older legacy path exists — `NotificationServiceImpl.sendOTP`, email
only, rate-limited 5-per-3-min in `NotificationController`. `OtpServiceImpl` is
the one carried here because it covers both channels.

### Error contract (never a 500)

| `DomainError` code | Raised when  | The view renders                            |
| ------------------ | ------------ | ------------------------------------------- |
| `OTP_RATE_LIMITED` | bucket empty | form error + cooldown hint                  |
| `OTP_EXPIRED`      | TTL passed   | form error + resend option                  |
| `OTP_INVALID`      | wrong code   | form error (attempts remaining decremented) |

### Wiring

- Delivery rides the existing `NotificationGateway` port (template key `send-otp`), so the code lands in Mailpit offline via [B2](B2-fake-adapters.md)'s fake.
- Audit events are **[A5](A5-workflow-state-machine.md)'s**, not this ticket's — no shim here.

## Acceptance criteria

- [x] Unit tests (locmem cache under test settings — no Redis needed): happy path, expiry, wrong-code cap → invalidation, issue-rate cap, resend cooldown, re-issue invalidates prior code, single-use enforced, SMS never emailed.
- [x] Constant-time comparison (`hmac.compare_digest`); the code is HMAC'd with `SECRET_KEY` at rest, never logged, and never crosses back to the caller — `send_otp` returns only a transaction id.
- [x] Works offline: `compose up` → OTP visible in Mailpit. Verified against the running stack:
  - **email** — sent from the django container to `mailpit:1025` over SMTP; Mailpit's API returned `Subject: [sandbox] send-otp`, `To: applicant@example.com`, body `code: 881855`, and the returned transaction id contained no trace of the code.
  - **phone** — `send_otp(+91…, SMS)` recorded `SMS -> +919876543210` and Mailpit's message count stayed at 1, i.e. a phone number is never emailed. Real SMS delivery is unverifiable until [B6](B6-notification-adapter.md) ships the adapter (no provider yet).
- [x] mypy/ruff clean.

## Out of scope (deferred)

Captcha (dropped by design) · the real SMS adapter ([B6](B6-notification-adapter.md) owns it; the fake records SMS sends so the flow is exercisable offline).

**SMS is not deferred.** Submit is blocked until both contacts are verified, so a
phone must be verifiable in v0. `send_otp` takes the channel and the caller
derives it from which contact is being verified — emailing a phone number is a
bug, and there is a regression test for it.
