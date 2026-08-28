# B7 — Provisioning chain + ledger + `PROVISIONING_FAILED` + console retry hook

> **Lane** B — Backend: integrations · **Phase** V0.3 · **the critical flow of v0**
> **Depends on** [B1](B1-integration-ports-http-policy.md), [B3](B3-keycloak-adapter.md), [B4](B4-wso2-adapter.md), [B5](B5-hiecm-adapter.md), [B6](B6-notification-adapter.md) · workflow events from [A5](A5-workflow-state-machine.md)
> **Unblocks** [B8](B8-deprovisioning-chain.md), [C7](C7-credentials-panel.md), the V0.3 exit criterion
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [03-database.md §3.4](../03-database.md)

## In plain words

When an application is approved, the integrator must end up with three things in three different systems: a Keycloak client, a WSO2 gateway subscription, and an HIE-CM bridge. This ticket is the background job that creates them **in order, exactly once** — keeping a ledger of what's already done so a crash-and-retry never creates duplicates. If a step ultimately fails, the application lands in a visible "provisioning failed" state with a retry button for admins that finishes only the missing pieces. This is the make-or-break flow of the whole pilot.

## Background

Provisioning is what the sandbox *is*: on approval the integrator must receive a Keycloak client, a WSO2 application + subscriptions, and an HIE-CM bridge. The legacy system ran this synchronously inside the request handler with **no idempotency** (a retry created duplicate Keycloak clients and WSO2 subscriptions), partial failures were silent, and a "provisioned" application could be missing half its resources.

v2: a Celery chain driven off the `SANDBOX_APPROVED` transition, with the `integrations_provisioned_resource` ledger as the idempotency backstop, explicit `PROVISIONING_FAILED` visibility, and a console-triggered manual retry. The V0.3 exit criterion runs through this ticket: *approval on staging provisions real sandbox credentials end-to-end; kill-mid-chain/retry proves idempotency*.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Celery chain: Keycloak → WSO2 → HIE-CM, ledger-checked steps | `sandbox/integrations/tasks.py` (or `provisioning.py`) |
| 2 | Trigger wiring: `SANDBOX_APPROVED` on-commit → chain → `PROVISIONING` | [A5](A5-workflow-state-machine.md) transition spec |
| 3 | Retry policy (max 5 / ~30 min) + terminal `PROVISIONING_FAILED` transition | chain |
| 4 | `retry_provisioning()` service for the console button | `sandbox/integrations/services.py` |
| 5 | Show-once secret handoff: short-TTL one-time-read cache (design shared with [C7](C7-credentials-panel.md)) | same |
| 6 | Completion: `PROVISIONED` transition + `sandbox-approved` notification | chain + [B6](B6-notification-adapter.md) |
| 7 | Tests vs fakes: happy path, kill/retry, terminal failure, retry-completes-missing | `sandbox/integrations/tests/` |

### Chain behaviour

- **Celery chain**, enqueued via `transaction.on_commit` of the `SANDBOX_APPROVED` transition; first step moves the application to `PROVISIONING` (via `transition()` — never direct writes). One step per system, **strict order** Keycloak → WSO2 → HIE-CM (WSO2 key-mapping needs the client; the bridge needs the client identity). Every step:
  1. checks the ledger for an existing `(application, system)` row → **skip if done** (idempotent re-runs);
  2. calls the adapter (idempotency key / create-or-lookup where the system supports it);
  3. on success writes the ledger row (`external_id`, `secret_ref` where applicable, `state=ACTIVE`);
  4. on error raises a structured failure (system, op, `AdapterError` detail).
- **Chain-level retry policy**: step failure retries with backoff, max 5 attempts over ~30 min; terminal failure → application `PROVISIONING_FAILED` (via `transition()`), failure detail recorded, admins notified (Sentry + console visibility).
- **Manual retry hook**: an idempotent service the console button ([C5](C5-console-review-queue.md)/[C7](C7-credentials-panel.md)) POSTs to — `PROVISIONING_FAILED → PROVISIONING`, re-enqueues the chain; completed steps skip via the ledger, only missing systems run.
- **Completion**: all three ledger rows ACTIVE → `PROVISIONED` transition; success side-effects: `sandbox-approved` notification ([B6](B6-notification-adapter.md)) linking to the credentials panel; the initial secret reaches [C7](C7-credentials-panel.md)'s show-once flow **without persistence** (short-TTL one-time-read cache keyed to the application — never a DB column, design reviewed with C7).
- Structured logs with correlation ID per step; ledger + state queryable by the [C7](C7-credentials-panel.md) polling partial.

## Acceptance criteria

- [ ] Happy path: approve → three ledger rows ACTIVE → `PROVISIONED`, notification sent (against fakes in CI, real systems on staging).
- [ ] **Kill mid-chain, re-run ⇒ no duplicates** (ledger-skip asserted; WireMock fault-injection version in [B9](B9-wiremock-fault-injection-suite.md)).
- [ ] Terminal failure lands `PROVISIONING_FAILED` with detail visible in console; retry provisions only the missing systems.
- [ ] All state moves via `transition()` and are audited; chain enqueue happens on commit only.
- [ ] No secret persisted anywhere (schema + log assertions).
- [ ] Staging: real end-to-end pass — issued credentials obtain a token and call a sandbox API through WSO2.

## Out of scope (deferred)

Drift-reconciliation sweep (P4) · deprovisioning ([B8](B8-deprovisioning-chain.md)) · callback registration/probes (P4).
