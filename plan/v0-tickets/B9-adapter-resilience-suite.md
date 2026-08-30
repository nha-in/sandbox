# B9 — Adapter resilience + chain idempotency suite

> **Lane** B — Backend: integrations · **Phase** V0.3 (contract half deferred past v0)
> **Depends on** [B1](B1-integration-ports-http-policy.md); exercises [B3](B3-keycloak-adapter.md)–[B8](B8-deprovisioning-chain.md)
> **Unblocks** V0.3 exit criterion (idempotency proof), CI confidence for the pilot
> **Refs** [06-integrations.md §3](../06-integrations.md) · [08-testing.md §3](../08-testing.md)

> Renamed from "WireMock contract + fault-injection suite". WireMock is the tool
> the resilience half happens to use, and naming the ticket after it hid the
> split that actually matters: **proving our behaviour under failure** (built,
> and tool-agnostic) versus **proving we speak ABDM's protocol** (deferred, and
> needing something other than WireMock — see below).

## In plain words

How do we know our connectors survive the real world — slow responses, crashes
mid-job, weird error payloads? We point the real adapters at a programmable HTTP
server and make it misbehave: stall past our timeout, sever the socket, fail five
times in a row. The headline test kills the provisioning job halfway, reruns it,
and proves from the server's own request log that nothing was created twice.
Runs in CI with no VPN.

## Background

Fakes ([B2](B2-fake-adapters.md)) prove the *domain* works; they cannot prove the
adapters behave under network failure. Neither can the `*_stub.py` transports in
`sandbox/integrations/tests/`: they replace httpx's transport, so no socket is
ever actually slow and no connection is ever actually dropped.

This is the safety net that makes "resilient adapters" a tested property instead
of a claim: the legacy system's silent partial provisioning and duplicate-on-retry
bugs are exactly what it exists to prevent.

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

- [x] All fault-injection assertions pass; breaker/retry/timeouts proven, not configured-and-hoped.
- [x] Kill/retry idempotency proven via the WireMock request journal for both chains (the V0.3 exit evidence).
- [x] Read-never-rotates guard test in place for Keycloak — asserted from the journal, where nothing else could see it.
- [x] Suite green in CI without network access; `WIREMOCK_REQUIRED=1` makes a missing container fail rather than skip.
- [x] Fixture layout + re-recording procedure documented in `tests/integrations/README.md`.
- [ ] Every B3-B6 adapter op has happy + error **contract** coverage against recorded fixtures — **deferred past v0**, and not with WireMock; see below.

### The contract half is deferred past v0

The ticket asked for fixtures "seeded from real sandbox-tier responses where
available, redacted". None are available: that is the open carry-over on
[B3](B3-keycloak-adapter.md)-[B6](B6-notification-adapter.md). Any fixture we
write today is our own reading of the legacy Java source — which is exactly what
the `*_stub.py` transports in `sandbox/integrations/tests/` already are, across
~85 tests covering every op's happy and error shapes.

Re-expressing the same guesses as WireMock JSON would add no information, double
the maintenance, and — the real objection — a directory named `fixtures/` implies
a recording nobody made.

What **is** built is everything that does not depend on knowing ABDM's payloads,
because it tests our own behaviour over a real socket:

- Timeouts are enforced, not merely configured. The stub transports replace
  httpx's transport, so a "timeout" test there raises `httpx.ReadTimeout` by
  hand — proving the `except` clause works, never that `read_timeout` was wired.
- Retry counts, and **zero** retries on non-idempotent POSTs, counted from the
  request journal rather than from our own bookkeeping.
- The breaker opening, refusing to touch the network, and half-opening after its
  reset window.
- Severed sockets and non-JSON bodies becoming typed `AdapterError`s.
- Both chains re-run without issuing a second create — a ledger that wrongly
  believed a step had run would pass the B7/B8 tests and fail here.

### When we come back to it, WireMock is probably the wrong tool

The contract job splits by system, and only half of it is blocked on NHA at all.

| System | Approach | Blocked on |
| --- | --- | --- |
| Keycloak | **Run the real thing.** `compose/local/keycloak` already does; [B3](B3-keycloak-adapter.md) was verified against it by hand. The gap is that the verification was never turned into a test. | nothing |
| WSO2 | **Run the real thing.** `wso2/wso2am` is published (4.3.0 and 4.5.0 both resolve) — the actual devportal API, so these would be real contract tests. Multi-GB image and slow start, so a nightly or opt-in job, not every PR. | nothing |
| HIE-CM | Recorded cassettes from staging. No public implementation exists. | NHA access |
| Notification | Recorded cassettes from staging. Same. | NHA access |

For the two that need recordings, **`vcrpy` / `pytest-recording` beats WireMock**
for one reason that matters: redaction is code, not a manual step.
`before_record_response` and `filter_headers` strip bearer tokens and
`consumerSecret` on the way to disk, so a recording *cannot* be committed
unredacted because somebody forgot. With WireMock you copy mappings out of a
container and redact by hand — one careless paste and a live credential is in git
history forever. Recording is also a flag (`--record-mode=once`) rather than a
proxy-mode container.

Two options considered and rejected:

- **Pact.** Its value is the *provider* verifying the contract against your
  expectations. ABDM will never run a Pact verification for us, so it collapses
  into a mock library with a broker attached.
- **Schemathesis / OpenAPI validation** is a reasonable middle rung rather than a
  rejection: Keycloak and WSO2 publish specs, so we could validate our requests
  and their responses without any live system. Weaker than running the container,
  much cheaper. Worth it if the WSO2 image proves too heavy for CI.

WireMock keeps the resilience half regardless. No cassette library injects
delays, severs sockets, or drives a breaker to half-open, so the end state is
both tools, not a replacement.

## Out of scope (deferred)

Load testing (P6) · contract tests for deferred ports (LGD, ReferenceEnv) · live-system smoke tests (covered by staging verification in B3–B8).
