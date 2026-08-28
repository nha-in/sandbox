# B5 — HIE-CM adapter (`BridgeRegistry`): bridge create/update/status

> **Lane** B — Backend: integrations · **Phase** V0.3
> **Depends on** [B1](B1-integration-ports-http-policy.md) · **real sandbox-tier HIE-CM access** (requested in V0.1) · Keycloak client identity from [B3](B3-keycloak-adapter.md)
> **Unblocks** [B7](B7-provisioning-chain.md), [B8](B8-deprovisioning-chain.md), [C7](C7-credentials-panel.md) (status)
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [07-infra-cicd.md §5](../07-infra-cicd.md)

## In plain words

HIE-CM is ABDM's registry of "bridges" — the record that says *this integrator's system is allowed to exchange health data, reachable at these endpoints*. It's the third and final thing provisioning creates. This connector registers the bridge, reports its status (which the credentials screen polls), and deactivates it when an application is rejected — closing another hole the legacy system left open.

## Background

The HIE-CM gateway is ABDM's bridge registry: an integrator's HIP/HIU endpoints are registered as a **bridge** tied to their client credentials — the third and final leg of provisioning (Keycloak client → WSO2 subscription → HIE-CM bridge). In the legacy system, bridge IDs were the derivable Keycloak client IDs (publicly visible), rejection never deactivated bridges, and the external URL rewrite (`/sandbox/v3/v1/*`) leaked into application config.

v2: the adapter uses **internal base URLs only** (the URL rewrite is IaC-owned, [07-infra-cicd.md §5](../07-infra-cicd.md)); bridge lifecycle is fully managed — created on provisioning, deactivated on rejection.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `HiecmBridgeRegistry` implementing `BridgeRegistry` (create / update / status / deactivate) | `sandbox/integrations/hiecm/adapter.py` |
| 2 | Gateway auth (session/token, cached) via the B1 factory | same |
| 3 | Contract + fault-injection coverage (with [B9](B9-wiremock-fault-injection-suite.md)) | `tests/integrations/hiecm/` |
| 4 | Staging verification note: bridge active after provisioning, inactive after rejection | ticket PR |

Implements `BridgeRegistry` using the [B1](B1-integration-ports-http-policy.md) factory:

```python
# integrations/hiecm/adapter.py — implements BridgeRegistry
class HiecmBridgeRegistry:
    def create_bridge(self, application: Application, client_id: str) -> BridgeCreated:
        """Registers the bridge for the integrator's client (identity derives from
        B3's non-derivable client_id). Create-or-verify: an existing bridge for
        the same client is success, not a duplicate (ledger re-runs)."""

    def update_bridge(self, external_id: str, ...) -> None:
        """v0 minimal — only what the SANDBOX flow requires (e.g. bridge URL).
        No speculative ops."""

    def get_bridge_status(self, external_id: str) -> BridgeStatus:
        """Typed status DTO; may be eventually-consistent — surface the raw
        state, callers interpret (B7 verification step, C7 polling partial)."""

    def deactivate_bridge(self, external_id: str) -> None:
        """Idempotent (B8). The legacy system never did this — bridges outlived
        rejected applications."""
```

- Auth per HIE-CM sandbox requirements (gateway session/token via the shared factory, cached with early refresh); errors → `AdapterError("HIECM", code, retryable)`.
- **Internal base URLs only** — the external URL rewrite (`/sandbox/v3/v1/*`) is IaC-owned, never in adapter config.

## Acceptance criteria

- [ ] Contract tests against WireMock fixtures ([B9](B9-wiremock-fault-injection-suite.md)): create, status, deactivate — happy + error shapes (duplicate, missing, 5xx).
- [ ] Create re-run safe; deactivate idempotent.
- [ ] No external/rewritten URLs in adapter config (internal base URLs only — config review).
- [ ] Timeouts/retry/breaker verified via fault injection.
- [ ] Verified end-to-end against real sandbox-tier HIE-CM from staging (bridge visible/active after provisioning; inactive after rejection).

## Out of scope (deferred)

Integrator callback registration + reachability probes (`applications_callback`, P4) · drift reconciliation of bridges (P4) · blocklist handling beyond surfacing status.
