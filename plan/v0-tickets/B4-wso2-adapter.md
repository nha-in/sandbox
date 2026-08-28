# B4 — WSO2 adapter (`ApiGateway`): app create, subscribe, unsubscribe

> **Lane** B — Backend: integrations · **Phase** V0.3
> **Depends on** [B1](B1-integration-ports-http-policy.md) · **real sandbox-tier WSO2 access** (requested in V0.1) · client relationship from [B3](B3-keycloak-adapter.md)
> **Unblocks** [B7](B7-provisioning-chain.md), [B8](B8-deprovisioning-chain.md)
> **Refs** [06-integrations.md §3–4](../06-integrations.md)

## In plain words

WSO2 is ABDM's API gateway — the front door every integrator's API call passes through. For credentials to actually work, the integrator needs a gateway "application" subscribed to the sandbox APIs and linked to their Keycloak client. This connector creates that application, subscribes it, links the keys, and — on rejection — unsubscribes it (which the legacy system never did, leaving rejected applicants with live API access).

## Background

WSO2 APIM is the ABDM API gateway: an approved integrator needs a WSO2 application subscribed to the sandbox API products, keyed to their Keycloak client, before their credentials call anything. The legacy `Wso2FClient` never actually called WSO2 — it **loopbacked over HTTP to the service's own `WSO2Controller`**, which then hit the DevPortal APIs with SSL verification disabled; admin credentials sat in git; rejection left subscriptions live forever.

v2 talks to the WSO2 DevPortal/Admin REST APIs directly through the shared http policy (WSO2 admin read timeout 15s), TLS verified, credentials from the secret store.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `Wso2ApiGateway` implementing `ApiGateway` (create / subscribe / map-keys / unsubscribe) | `sandbox/integrations/wso2/adapter.py` |
| 2 | SANDBOX product set + throttle/grant/scope config as typed settings | `config/settings/*` |
| 3 | Contract + fault-injection coverage (with [B9](B9-wiremock-fault-injection-suite.md)) | `tests/integrations/wso2/` |
| 4 | Staging verification note: real app subscribed, token accepted by the gateway | ticket PR |

Implements `ApiGateway` using the [B1](B1-integration-ports-http-policy.md) factory:

```python
# integrations/wso2/adapter.py — implements ApiGateway
class Wso2ApiGateway:
    def create_application(self, application: Application) -> GatewayAppCreated:
        """Create-or-lookup by our deterministic app name —
        ledger-driven re-runs must not duplicate."""

    def subscribe(self, external_id: str) -> None:
        """Subscribes to the SANDBOX API product set. Throttle policy /
        grant types / scopes come from typed per-kind settings, not hardcoded."""

    def map_keys(self, external_id: str, client_id: str) -> None:
        """Associates the Keycloak client with the WSO2 app so gateway JWT
        validation works. The one place a secret_ref may be dereferenced —
        fetched transiently, never stored or logged."""

    def unsubscribe(self, external_id: str) -> None:
        """Idempotent: already-unsubscribed/missing is success (B8).
        Also retires the application."""
```

- Errors → `AdapterError("WSO2", code, retryable)`; pagination handled where list APIs page.
- TLS verified everywhere (the legacy system disabled it); credentials from the secret store only.

## Acceptance criteria

- [ ] Contract tests against WireMock fixtures ([B9](B9-wiremock-fault-injection-suite.md)): create, subscribe, map-keys, unsubscribe — happy + error shapes (409 duplicate, 404 missing, 5xx).
- [ ] Create/subscribe re-run safe (create-or-lookup asserted — no duplicate apps/subscriptions).
- [ ] Unsubscribe idempotent; TLS verification on (no `verify=False` anywhere — grep-able assertion).
- [ ] Timeouts (15s admin), retry, breaker verified via fault injection; no credentials outside the secret store.
- [ ] Verified end-to-end against real sandbox-tier WSO2 from staging.

## Out of scope (deferred)

`get_usage` milestone evidence (P4, flag-gated) · key rotation on WSO2 side · per-kind product sets beyond SANDBOX.
