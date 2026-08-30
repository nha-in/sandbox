# B1 — `integrations` ports + shared HTTP policy (timeouts/retry/breaker/DTOs)

> **Lane** B — Backend: integrations · **Phase** V0.3 Credentials (can start the moment V0.1 lands)
> **Depends on** V0.1 only
> **Unblocks** everything in Lane B ([B2](B2-fake-adapters.md)–[B9](B9-adapter-resilience-suite.md))
> **Refs** [06-integrations.md §2–3](../06-integrations.md) · [01-backend.md §3.1](../01-backend.md)

## In plain words

The sandbox has to talk to four external systems it doesn't control (Keycloak, WSO2, HIE-CM, an email gateway). Other people's systems hang, error and half-finish — so all conversation with them goes through one guarded doorway: clean Python interfaces ("ports") that the rest of the app uses, and one shared HTTP engine that enforces time limits, careful retries and circuit breakers. This ticket builds the doorway and the engine; the four actual connectors ([B3](B3-keycloak-adapter.md)–[B6](B6-notification-adapter.md)) plug into it.

## Background

The legacy system called Keycloak, WSO2, HIE-CM and the notification gateway through six Feign clients with **zero timeouts, zero retries, zero circuit breakers** — any dependency hang propagated straight into request threads. One client (`getSecret`) was even bound to POST, silently rotating the secret on every "read".

v2 puts every external call behind an **anti-corruption layer**: typed ports (Protocols) + one shared httpx client policy. Domain code never imports httpx and never sees external JSON shapes. This ticket lays that foundation; the concrete adapters ([B3](B3-keycloak-adapter.md)–[B6](B6-notification-adapter.md)) plug into it.

## What to build

### Deliverables

| #   | Deliverable                                                       | Where                            |
| --- | ----------------------------------------------------------------- | -------------------------------- |
| 1   | Port Protocols + typed DTOs + `AdapterError`                      | `sandbox/integrations/ports.py`  |
| 2   | Shared httpx client factory (timeouts/retry/breaker/auth/tracing) | `sandbox/integrations/http.py`   |
| 3   | `ProvisionedResource` ledger model + migration (schema only)      | `sandbox/integrations/models.py` |
| 4   | Import-linter contract: domain → ports only                       | `pyproject.toml`                 |
| 5   | Settings toggle: port → real adapter / fake per environment       | `config/settings/*`              |
| 6   | Unit tests for every http-policy behaviour                        | `sandbox/integrations/tests/`    |

> **Deliverable 3 landed later, once [A3](A3-applications-model.md) shipped.** The
> ledger's `application` FK and its `UNIQUE (application, system)` backstop both
> require `applications.Application`, so deliverables 1, 2, 4, 5 and 6 went first
> and unblocked [B2](B2-fake-adapters.md)–[B6](B6-notification-adapter.md); the
> ledger followed, before [B7](B7-provisioning-chain.md)/[B8](B8-deprovisioning-chain.md)
> need it.

### Layout

```
sandbox/integrations/
├── ports.py        # Protocols: IdpAdmin, ApiGateway, BridgeRegistry, NotificationGateway
├── http.py         # shared httpx client factory
├── models.py       # ProvisionedResource ledger (schema here; chain logic in B7)
├── fakes.py        # B2
└── {keycloak,wso2,hiecm,notification}/adapter.py   # B3–B6
```

### Ports (`ports.py`)

v0 ports as `typing.Protocol`s with **typed DTOs** (dataclasses/pydantic) for every request/response. Exact signatures are settled in [B3](B3-keycloak-adapter.md)–[B6](B6-notification-adapter.md) — the Protocol + DTO shape is the contract this ticket owns. (`LgdLookup`/`ReferenceEnv` are deferred — don't stub them.)

```python
class IdpAdmin(Protocol):             # Keycloak — B3
    def create_client(...) -> ClientCreated: ...
    def rotate_client_secret(...) -> SecretRotated: ...
    def disable_client(...) -> None: ...

class ApiGateway(Protocol):           # WSO2 — B4
    def create_application(...) -> GatewayAppCreated: ...
    def subscribe(...) -> None: ...
    def map_keys(...) -> None: ...
    def unsubscribe(...) -> None: ...

class BridgeRegistry(Protocol):       # HIE-CM — B5
    def create_bridge(...) -> BridgeCreated: ...
    def get_bridge_status(...) -> BridgeStatus: ...
    def deactivate_bridge(...) -> None: ...

class NotificationGateway(Protocol):  # B6
    def send(...) -> SendResult: ...
```

- **`AdapterError(system, code, retryable)`** — the only exception type adapters may raise; unexpected response shapes must raise it rather than leak.
- **Ports take DTOs, never domain models.** `create_client(spec: ClientSpec)` rather than
  `create_client(application: Application)`: a port that imported `Application` would point
  the dependency arrow back at the domain and defeat the anti-corruption layer. Adapters
  never see an ORM object; the caller maps.
- **DTOs carrying a secret set `repr=False` on that field**, so a traceback or a naive log
  line cannot leak it.

### Shared client policy (`http.py`)

Client factory applying to every adapter:

| Concern         | Policy                                                                                                                                         |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Timeouts        | explicit per adapter: connect 3s; read 10s default (notification 5s, WSO2 admin 15s) — **no unbounded calls**                                  |
| Retries         | tenacity: idempotent ops only, exponential backoff + jitter, max 3 — never retry non-idempotent POSTs without an idempotency guarantee         |
| Circuit breaker | pybreaker per system: open after 5 consecutive failures, half-open probe 30s; breaker state loggable/exposable                                 |
| Auth            | server-side credentials from env/secret store; token caching with early refresh                                                                |
| Tracing         | correlation-ID + `traceparent` headers on every call; one structured log line per call (system, op, duration, outcome) — **never log secrets** |

### Provisioning ledger (schema only — chain logic is [B7](B7-provisioning-chain.md))

`integrations_provisioned_resource`:

| Field          | Type             | Constraints / notes                                                             |
| -------------- | ---------------- | ------------------------------------------------------------------------------- |
| `application`  | FK → application | `PROTECT` — the ledger outlives cleanup scripts                                 |
| `system`       | char + CHECK     | `KEYCLOAK \| WSO2 \| HIECM`                                                     |
| `external_ref` | char             | id in the external system — **not** `external_id`, see below                    |
| `secret_ref`   | char             | secret-store reference only — **never a secret value**                          |
| `state`        | char + CHECK     | `ACTIVE \| DISABLED \| FAILED \| ORPHANED`                                      |
| —              |                  | `UNIQUE (application, system) WHERE deleted = false` — the idempotency backstop |

> **`external_ref`, not `external_id`.** This ticket originally specified
> `external_id` for "id in the external system", which collides with
> `BaseModel.external_id` — our own public UUID. Declaring it does not error:
> Django silently replaces the inherited field, and the first generated migration
> had a single `CharField`, leaving the ledger with no identifier of its own and
> no unique index on it. mypy caught the type change; nothing else would have.
> `external_ref` is the name [03-database.md](../03-database.md)'s ERD already
> used, and it pairs with `secret_ref`.

### Boundaries

- **Import-linter contract**: domain apps may import `integrations.ports`/DTOs only; httpx/adapter modules are off-limits outside `integrations/`.
- Settings toggle mapping each port → real adapter or fake ([B2](B2-fake-adapters.md)); local defaults to fakes.

## Acceptance criteria

- [x] Ports + DTOs defined, mypy-strict clean; adapters interchangeable with fakes behind settings.
- [x] http factory unit-tested: timeout honored, retry count on idempotent op, no retry on non-idempotent op, breaker opens after 5 failures and half-opens after 30s.
- [x] `AdapterError` carries system/code/retryable; unknown shapes mapped, not propagated.
- [x] Ledger migration applied; uniqueness enforced. — asserted against the database, including that a soft-deleted row frees the slot for re-provisioning.
- [x] Import-linter contract green in CI.

### Decisions taken while building

| Question                              | Decision                                                                                                                                                                 |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| What counts as one breaker "failure"? | A **fully-retried** request. Breaker wraps retry, so an open circuit short-circuits without burning attempts, and `CIRCUIT_OPEN` surfaces as a retryable `AdapterError`. |
| Do 4xx responses trip the breaker?    | **No.** A 404 means we asked wrongly, not that the dependency is down; only retryable errors count toward `fail_max`.                                                    |
| Which methods retry by default?       | `GET/HEAD/OPTIONS/PUT/DELETE`. POST must pass `idempotent=True` explicitly, forcing the author to name the idempotency guarantee.                                        |
| Breaker scope                         | One per `ExternalSystem`, shared by every client pointed at it — WSO2 being down must not open Keycloak's circuit.                                                       |
| httpx's own logging                   | Silenced to `WARNING` in `LOGGING`. It emitted a second INFO line per call containing the full URL; our structured line is the record of truth.                          |

## Out of scope (deferred)

`LgdLookup` + `ReferenceEnv` ports (P4) · Prometheus metric export of breaker state (P4/P6 — structured logs suffice in v0) · drift-reconciliation sweep (P4).
