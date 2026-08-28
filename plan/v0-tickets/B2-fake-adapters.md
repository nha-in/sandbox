# B2 ⚑ — Fake adapters for every port (offline dev unblocked)

> **Lane** B — Backend: integrations · **Phase** V0.3 · **⚑ junior-suitable starter**
> **Depends on** [B1](B1-integration-ports-http-policy.md)
> **Unblocks** offline dev for Lanes A/C, [A9](A9-seed-sandbox-demo.md), [C9](C9-playwright-e2e.md) e2e, CI
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [07-infra-cicd.md §3](../07-infra-cicd.md)

## In plain words

Developers must be able to run the whole portal on a laptop with no VPN and no access to the real government systems. So every external connector gets a **stand-in**: a fake Keycloak that hands out pretend credentials, a fake gateway, a fake bridge registry, and a fake email sender that drops mail into the local Mailpit inbox. The fakes behave realistically — including *failing on demand*, so we can rehearse the failure screens without breaking anything real.

## Background

Local dev must require **no VPN and no live ABDM systems**: `docker compose up` + seeds + fakes = fully working portal. That rule is what lets Lane A/C build and test the provisioning UX before (and independent of) real sandbox-tier access. The fakes are also what Playwright e2e runs against in CI — they are a permanent deliverable, not scaffolding.

One in-process fake per port from [B1](B1-integration-ports-http-policy.md), selected by settings (`local`/`test` default to fakes; WireMock stays the CI *contract* harness — different job, [B9](B9-wiremock-fault-injection-suite.md)).

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `FakeIdpAdmin`, `FakeApiGateway`, `FakeBridgeRegistry`, `FakeNotificationGateway` | `sandbox/integrations/fakes.py` |
| 2 | Failure-injection knobs (fail-next, latency, always-fail) | same + settings/test API |
| 3 | Pytest reset fixture + seed pre-population hooks for [A9](A9-seed-sandbox-demo.md) | `conftest.py` / fakes |
| 4 | Offline-dev section in the repo README | `README.md` |

### Details

- One fake per port, state in-process (dict) or Redis where cross-process visibility is needed (e.g. Celery worker + web both see a created client):
  - **`FakeIdpAdmin`** — create/disable client (plausible client_id + generated secret), rotate secret (returns a new one — show-once flow must work), role assignment recorded; "get" ops never mutate.
  - **`FakeApiGateway`** — create application, subscribe, unsubscribe; stable fake IDs.
  - **`FakeBridgeRegistry`** — create/update bridge, bridge status with a realistic pending→active progression (lets [C7](C7-credentials-panel.md) demo polling).
  - **`FakeNotificationGateway`** — delivers email via Django's email backend so messages appear in **Mailpit** locally (OTP + lifecycle emails must be visually checkable) and records sends for assertions.
- **Failure injection knobs** (settings/env or a tiny test API): fail-next-call(system, op), latency injection, always-fail — needed by [B7](B7-provisioning-chain.md)/[B8](B8-deprovisioning-chain.md) tests and manual `PROVISIONING_FAILED` demos.
- Deterministic + resettable between tests (pytest fixture); seeds ([A9](A9-seed-sandbox-demo.md)) can pre-populate fake state so PROVISIONED apps look consistent.
- Document the offline story in the repo README (compose + seed + fakes).

## Acceptance criteria

- [ ] Every v0 port has a fake conforming to the Protocol (mypy-checked).
- [ ] Full journey works offline: enroll → approve → provisioning completes against fakes → credentials shown → rotate works → reject deprovisions.
- [ ] OTP + lifecycle emails visible in Mailpit locally.
- [ ] Failure injection demonstrably drives `PROVISIONING_FAILED` + console retry.
- [ ] Fakes reset cleanly between tests; used by default in `local`/`test` settings.

## Out of scope

Fakes for deferred ports (LGD, ReferenceEnv) · WireMock fixtures ([B9](B9-wiremock-fault-injection-suite.md)).
