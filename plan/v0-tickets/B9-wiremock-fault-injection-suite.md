# B9 — WireMock contract + fault-injection suite

> **Lane** B — Backend: integrations · **Phase** V0.3 (fixtures grow alongside B3–B8)
> **Depends on** [B1](B1-integration-ports-http-policy.md); exercises [B3](B3-keycloak-adapter.md)–[B8](B8-deprovisioning-chain.md)
> **Unblocks** V0.3 exit criterion (idempotency proof), CI confidence for the pilot
> **Refs** [06-integrations.md §3](../06-integrations.md) · [08-testing.md §3](../08-testing.md)

## In plain words

How do we know our connectors survive the real world — slow responses, crashes mid-job, weird error payloads? We test them against a **programmable pretend network** (WireMock): it replays recorded real responses to prove we speak each system's protocol, and it injects delays and failures to prove our time limits, retries and circuit breakers actually fire. The headline test kills the provisioning job halfway, reruns it, and proves nothing gets created twice. Runs in CI with no VPN.

## Background

Fakes ([B2](B2-fake-adapters.md)) prove the *domain* works; they cannot prove the adapters speak the real protocols or behave under network failure. That is this suite's job: recorded WireMock fixtures per system as the **contract harness**, plus latency/fault rules as the **resilience harness**. It runs in CI on every PR touching `integrations/` — no VPN, no live systems.

This is the safety net that makes "resilient adapters" a tested property instead of a claim: the legacy system's silent partial provisioning and duplicate-on-retry bugs are exactly what this suite exists to prevent.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | WireMock harness (compose test profile or testcontainers) + pytest fixtures pointing **real adapters** at it | `tests/integrations/conftest.py` |
| 2 | Recorded, redacted fixtures per system | `tests/integrations/fixtures/{keycloak,wso2,hiecm,notification}/` |
| 3 | Contract tests: every adapter op, happy + error shapes | `tests/integrations/test_contract_*.py` |
| 4 | Fault-injection tests: timeout, retry counts, breaker, malformed JSON | `tests/integrations/test_faults_*.py` |
| 5 | Chain idempotency proofs via the WireMock request journal (both chains) | `tests/integrations/test_chains.py` |
| 6 | CI job wiring + fixture re-recording guide | pipeline + test README |

### Details

- **Harness**: fixture recordings seeded from real sandbox-tier responses where available, redacted.
- **Contract tests** per adapter — happy path + error shapes:
  - Keycloak: token, create client, roles-by-name lookup + mapping, rotate, disable; 401/409/404/5xx shapes; **a stub that fails the suite if any read op hits `POST /client-secret`**.
  - WSO2: create app, subscribe, map-keys, unsubscribe; duplicate-subscription 409; pagination shape.
  - HIE-CM: bridge create/status/deactivate; duplicate + missing-bridge shapes.
  - Notification: send; template-error + 5xx shapes.
- **Fault-injection tests** (WireMock delay/fault rules) asserting [B1](B1-integration-ports-http-policy.md) policy end-to-end:
  - read timeout honored per adapter (fixed delay > read timeout ⇒ `AdapterError` in bounded time, no hang);
  - retry counts on idempotent ops (exactly max-3, backoff observed); **zero retries** on non-idempotent POSTs;
  - breaker opens after 5 consecutive failures (6th call fails fast, no HTTP hit), half-open probe after 30s (clock-mocked);
  - malformed/unexpected JSON ⇒ typed `AdapterError`, not a parse crash.
- **Chain idempotency proofs** (the headline tests, run against WireMock):
  - **provisioning kill/retry**: fail step 2 of Keycloak→WSO2→HIE-CM, re-run chain ⇒ step 1 skipped via ledger, **WireMock request journal shows zero duplicate create calls**;
  - **deprovisioning kill/retry**: same property on the reverse chain;
  - terminal-failure path: exhaust retries ⇒ `PROVISIONING_FAILED`, then console-retry completes only missing steps.
- CI wiring: suite runs headless in the pipeline; fixture-update workflow documented (how to re-record when an API changes).

## Acceptance criteria

- [ ] Every B3–B6 adapter op has happy + error contract coverage; suite green in CI without network access.
- [ ] All fault-injection assertions above pass; breaker/retry/timeouts proven, not configured-and-hoped.
- [ ] Kill/retry idempotency proven via the WireMock request journal for both chains (this is the V0.3 exit evidence).
- [ ] Read-never-rotates guard test in place for Keycloak.
- [ ] Fixture layout + re-recording procedure documented in the test README.

## Out of scope (deferred)

Load testing (P6) · contract tests for deferred ports (LGD, ReferenceEnv) · live-system smoke tests (covered by staging verification in B3–B8).
