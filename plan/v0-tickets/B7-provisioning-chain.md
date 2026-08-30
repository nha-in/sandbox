# B7 — Provisioning chain + ledger + `PROVISIONING_FAILED` + console retry hook

> **Lane** B — Backend: integrations · **Phase** V0.3 · **the critical flow of v0**
> **Depends on** [B1](B1-integration-ports-http-policy.md), [B3](B3-keycloak-adapter.md), [B4](B4-wso2-adapter.md), [B5](B5-hiecm-adapter.md), [B6](B6-notification-adapter.md) · workflow events from [A5](A5-workflow-state-machine.md)
> **Unblocks** [B8](B8-deprovisioning-chain.md), [C7](C7-credentials-panel.md), the V0.3 exit criterion
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [03-database.md §3.4](../03-database.md)

## In plain words

When an application is approved, the integrator must end up with three things in three different systems: a Keycloak client, a WSO2 gateway subscription, and an HIE-CM bridge. This ticket is the background job that creates them **in order, exactly once** — keeping a ledger of what's already done so a crash-and-retry never creates duplicates. If a step ultimately fails, the application lands in a visible "provisioning failed" state with a retry button for admins that finishes only the missing pieces. This is the make-or-break flow of the whole pilot.

## Background

Provisioning is what the sandbox _is_: on approval the integrator must receive a Keycloak client, a WSO2 application + subscriptions, and an HIE-CM bridge. The legacy system ran this synchronously inside the request handler with **no idempotency** (a retry created duplicate Keycloak clients and WSO2 subscriptions), partial failures were silent, and a "provisioned" application could be missing half its resources.

v2: a Celery chain driven off the `SANDBOX_APPROVED` transition, with the `integrations_provisioned_resource` ledger as the idempotency backstop, explicit `PROVISIONING_FAILED` visibility, and a console-triggered manual retry. The V0.3 exit criterion runs through this ticket: _approval on staging provisions real sandbox credentials end-to-end; kill-mid-chain/retry proves idempotency_.

## What to build

### Deliverables

| #   | Deliverable                                                                                                | Where                                                  |
| --- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| 1   | Celery chain: Keycloak → WSO2 → HIE-CM, ledger-checked steps                                               | `sandbox/integrations/tasks.py` (or `provisioning.py`) |
| 2   | Trigger wiring: `SANDBOX_APPROVED` on-commit → chain → `PROVISIONING`                                      | [A5](A5-workflow-state-machine.md) transition spec     |
| 3   | Retry policy (max 5 / ~30 min) + terminal `PROVISIONING_FAILED` transition                                 | chain                                                  |
| 4   | `retry_provisioning()` service for the console button                                                      | `sandbox/integrations/services.py`                     |
| 5   | Show-once secret handoff: short-TTL one-time-read cache (design shared with [C7](C7-credentials-panel.md)) | same                                                   |
| 6   | Completion: `PROVISIONED` transition + `sandbox-approved` notification                                     | chain + [B6](B6-notification-adapter.md)               |
| 7   | Tests vs fakes: happy path, kill/retry, terminal failure, retry-completes-missing                          | `sandbox/integrations/tests/`                          |

### Chain behaviour

- **Celery chain**, enqueued via `transaction.on_commit` of the `SANDBOX_APPROVED` transition; first step moves the application to `PROVISIONING` (via `transition()` — never direct writes). One step per system, **strict order** Keycloak → WSO2 → HIE-CM (WSO2 key-mapping needs the client; the bridge needs the client identity). Every step:
  1. checks the ledger for an existing `(application, system)` row → **skip if done** (idempotent re-runs);
  2. calls the adapter (idempotency key / create-or-lookup where the system supports it);
  3. on success writes the ledger row (`external_ref`, `secret_ref` where applicable, `state=ACTIVE`);
  4. on error raises a structured failure (system, op, `AdapterError` detail).
- **Chain-level retry policy**: step failure retries with backoff, max 5 attempts over ~30 min; terminal failure → application `PROVISIONING_FAILED` (via `transition()`), failure detail recorded, admins notified (Sentry + console visibility).
- **Manual retry hook**: an idempotent service the console button ([C5](C5-console-review-queue.md)/[C7](C7-credentials-panel.md)) POSTs to — `PROVISIONING_FAILED → PROVISIONING`, re-enqueues the chain; completed steps skip via the ledger, only missing systems run.
- **Completion**: all three ledger rows ACTIVE → `PROVISIONED` transition; success side-effects: `sandbox-approved` notification ([B6](B6-notification-adapter.md)) linking to the credentials panel; the initial secret reaches [C7](C7-credentials-panel.md)'s show-once flow **without persistence** (short-TTL one-time-read cache keyed to the application — never a DB column, design reviewed with C7).
- Structured logs with correlation ID per step; ledger + state queryable by the [C7](C7-credentials-panel.md) polling partial.
- **Carry the correlation id into every task explicitly.** `sandbox.utils.correlation` holds it in a `ContextVar`, which is per-process, so it does **not** survive `transaction.on_commit` → broker → worker: a chain that does nothing will start a fresh id, and the approval will not be linked to the provisioning it caused — the exact case the field exists for. Pass the id from `get_correlation_id()` as a task argument (or a message header) and call `set_correlation_id()` as the first line of each task. Then [A5](A5-workflow-state-machine.md)'s audit rows, this chain's audit rows, and the `X-Correlation-Id`/`traceparent` headers [B1](B1-integration-ports-http-policy.md) sends to Keycloak/WSO2/HIE-CM all share one value. Worth a test: approve, run the chain, assert every `audit_event` row for that application has the same `correlation_id`.

### Worth considering: per-application role sets

v0 grants `keycloak.roles.role_names_for(kind)` — one fixed set per application
kind. A finer grant is possible without weakening anything, because the
applicant already declares `integration_intents` in the [A3](A3-applications-model.md)
payload (`ABHA_M1`, `HIP_M2`, `HIU_M3`, `HPR_HFR_M4`), and a reviewer approves
that payload before provisioning runs. Mapping approved intents → role names
server-side would let an integrator building only a HIP receive only `hip`.

The rule that must survive any such change: **role names never come from a
request.** They are derived from an approved, server-held record. A client that
can name its own roles can name all fourteen, which is the legacy over-grant
with extra steps ([05-security.md](../05-security.md) §3: no client-side role
checks). A console screen letting a reviewer narrow the set is fine on the same
terms — options from a server-side allowlist, validated on POST.

Blocked on the same thing [B3](B3-keycloak-adapter.md) is: open question 4, where
NHA still owes the per-kind role subset. Building an intent→role map onto role
names we cannot yet validate would be premature.

## Acceptance criteria

- [x] Happy path: approve → three ledger rows ACTIVE → `PROVISIONED`, notification sent (against fakes in CI).
- [x] **Kill mid-chain, re-run ⇒ no duplicates** (ledger-skip asserted; WireMock fault-injection version in [B9](B9-wiremock-fault-injection-suite.md)).
- [x] Terminal failure lands `PROVISIONING_FAILED` with detail on the transition comment; retry provisions only the missing systems.
- [x] All state moves via `transition()` and are audited; chain enqueue happens on commit only.
- [x] No secret persisted anywhere (asserted: the value appears in no ledger column, and the ref is read exactly once).
- [x] One correlation id spans the approval and every task the chain runs (asserted across `audit_event`).
- [ ] Staging: real end-to-end pass — issued credentials obtain a token and call a sandbox API through WSO2. **Blocked on NHA**, and on `WSO2_API_NAMES`, which has no default.

### Decisions worth knowing

- **One extra ledger column, `public_ref`.** Keycloak is the only system with two
  handles: `external_ref` is the internal UUID that `disable_client` and
  `rotate_client_secret` take, and the OAuth `clientId` is what C7 shows, what
  WSO2 maps as its consumer key, and what the HIE-CM bridge is named after. A
  retry that skips the Keycloak step has to read both back from the ledger, so
  neither could be left to travel only through the chain's arguments.
- **The chain is four Celery tasks, not one.** Each retries on its own budget,
  and `CELERY_TASK_SOFT_TIME_LIMIT` is 60s — Keycloak's create-plus-role-grants
  alone would risk that in a single task.
- **A parked run stops the remaining links by state, not by exception.** Every
  step returns early unless the application is in `PROVISIONING`, so the chain
  does not depend on Celery's error-propagation semantics to avoid running WSO2
  after Keycloak has already failed.
- **`ImproperlyConfigured` is terminal, not retryable.** A missing API-name list
  will not fix itself in half an hour; retrying only delays the operator.
- **`complete_provisioning` reads the ledger.** "The chain got this far" is not
  evidence: it re-checks that all three systems are ACTIVE and parks the
  application if not, because `PROVISIONED` is a claim about three systems.
- **Failure writes no phantom ledger row.** Absence already means "not
  provisioned"; a row with an empty `external_ref` would have to be reasoned
  about by every later reader, including B8.
- **The parked secret outlives its TTL by rotating, not by waiting.**
  `SECRET_REF_TTL_SECONDS` is 900s and this chain's retry budget is
  `120+240+480+900` = 1740s, so a WSO2 outage lasting past the TTL would reach a
  step that can never succeed: Keycloak is already ACTIVE so it is skipped, and
  nothing else mints a replacement. The WSO2 step now re-mints via
  `rotate_client_secret` when the ref has aged out, which is the second reason
  `external_ref` is on the ledger.
- **The WSO2 fake dereferences the secret ref, as the real adapter does.** It
  used to store the ref without reading it, which is exactly why the expiry
  dead-end above was invisible against the fakes.

- **Residual duplicate window, and it is Keycloak only.** WSO2 and HIE-CM both
  recover on their own: `create_application` is create-or-lookup on
  `sbx-{reference}` and adopts the winner of a 409, and `create_bridge` is a PUT
  against a bridge id we choose, so both re-runs converge on the resource the
  last attempt made. `create_client` is a plain POST with a fresh **random**
  client id, so a crash between the remote create and the ledger write orphans
  it — and lookup cannot rescue that either, because the random id was the only
  handle and it died with the task. Making the client id derivable from
  `application.external_id` would close it, at the cost of B3's rule that ids are
  not guessable from anything public; P4's reconciliation sweep is the cheaper
  answer and owns this today.

## Out of scope (deferred)

Drift-reconciliation sweep (P4) · deprovisioning ([B8](B8-deprovisioning-chain.md)) · callback registration/probes (P4).
