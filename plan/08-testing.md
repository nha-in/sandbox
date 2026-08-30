# 08 — Testing

**Parent:** [00-master-plan.md](00-master-plan.md) · **Audience:** every engineer — gates run in CI ([07-infra-cicd.md](07-infra-cicd.md))

---

## 1. In plain words

The legacy system's tests didn't even compile, so quality lived in people's heads. Here, the test suite *is* the specification of what must never break: every workflow move (legal and illegal) is asserted; every URL is listed in a table saying who may open it — and adding a URL without a row **fails the build**; the integrations are tested against a fake network that injects timeouts and crashes to prove our retries and circuit breakers actually work; and a robot browser walks the entire integrator journey — once normally and once with JavaScript switched off, proving the portal works as plain HTML.

## 2. Legacy findings

45 backend test files that don't compile (JUnit 4 on a JUnit 5 classpath); 26 FE test files for 291 sources; no CI. Effective coverage ≈ zero — which is why the bar below is explicit.

## 3. Design — the test pyramid

| Layer | Tooling | Scope |
|---|---|---|
| Unit | pytest | services, selectors, forms/validators, state-machine guards (full table, legal + illegal) |
| DB/model | pytest-django | constraints (partial-unique live app incl. `deleted=false`, review uniqueness), migrations from zero, seed idempotency |
| **Route-gate matrix** | pytest-django | §4 — the authz proof ([C3](v0-tickets/C3-route-gate-harness.md)) |
| View/partial | pytest-django + test client | pages render, partials swap, **every mutation works as a plain POST** (htmx-off), messages/redirects correct |
| Adapter resilience | pytest + WireMock | real-socket timeouts, retry counts, breaker open/half-open, severed sockets, chain kill/retry idempotency from the request journal ([B9](v0-tickets/B9-adapter-resilience-suite.md)). Per-system contract coverage is stub-transport level until a real container or a recording exists — see B9. |
| e2e | Playwright vs compose + seed | the full journey + branch scenarios; one pass with JavaScript disabled ([C9](v0-tickets/C9-playwright-e2e.md)) |
| Load | Locust/k6 | v1 (P6): 10k+ applications, p95 TTFB budgets per URL group |
| Parity | golden-data harness | v1 (P5): reporting numbers vs a legacy snapshot before cutover |

### 4. Route-gate matrix (the centrepiece)

Every named URL is enumerated in `tests/test_route_gates.py` as (url, method) × actor ∈ {anonymous, member-of-other-org, org member, reviewer, staff} with the expected status:

- Adding a URL without a matrix row fails CI (the test introspects the URLconf and diffs).
- Org-scoped objects resolve **404** for the wrong org (never 403 — existence must not leak).
- Console URLs: non-staff always 403/redirect, verified per route — a forgotten mixin is caught.

## 5. v0 (POC)

All pyramid layers except load + parity, over the SANDBOX journey:

- Quality gates in CI: coverage ≥ 85% on `services/`, `selectors/`, `workflow/`, `integrations/` (templates excluded — covered by view + e2e layers); mypy strict on the same modules; ruff/djLint clean.
- Playwright smoke (login, dashboard, one mutation) on every PR; full suite incl. **JS-disabled full pass** on main.
- Fault-injection suite green — kill/retry idempotency proofs are the V0.3 exit evidence.

**Exit criteria:** transition table 100% covered; matrix complete + drift check active; JS-disabled e2e green; seed idempotency proven.

## 6. v1 — everything else

| Item | Phase |
|---|---|
| Load tests: 10k+ seeded applications, p95 TTFB budgets, dashboard queries | P6 |
| Golden-data parity harness vs a legacy snapshot (gates reporting cutover) | P5 |
| axe-core accessibility assertions inside Playwright on the six core journeys | P6 |
| e2e coverage for new kinds, conformance runs, tickets, docs portal as they ship | P2–P5 |
| Pen test (with [05-security.md](05-security.md)) | P6 |

## 7. Definition of done

**v0**

- [ ] Transition table 100% covered incl. every illegal transition.
- [ ] Route-gate matrix complete + URLconf drift check active.
- [ ] Fault-injection suite green; chain idempotency proven under kill/retry.
- [ ] JS-disabled e2e pass green.

**v1**

- [ ] Load budgets met; parity harness signed off before cutover; axe-core green on the six journeys.
