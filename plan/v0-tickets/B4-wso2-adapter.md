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

| #   | Deliverable                                                                              | Where                                      |
| --- | ---------------------------------------------------------------------------------------- | ------------------------------------------ |
| 1   | `Wso2ApiGateway` implementing `ApiGateway` (create / subscribe / map-keys / unsubscribe) | `sandbox/integrations/wso2/adapter.py`     |
| 2   | SANDBOX API-name set + throttle/key config as typed settings                             | `config/settings/base.py` + `wso2/apis.py` |
| 3   | Contract + fault-injection coverage (with [B9](B9-wiremock-fault-injection-suite.md))    | `sandbox/integrations/tests/test_wso2.py`  |
| 4   | Staging verification note: real app subscribed, token accepted by the gateway            | ticket PR                                  |

Implements the `ApiGateway` protocol as [B1](B1-integration-ports-http-policy.md)
shipped it — DTOs in, no domain models, so the dependency arrow stays pointed
away from the domain:

```python
# integrations/wso2/adapter.py — implements ApiGateway
class Wso2ApiGateway:
    def create_application(self, spec: GatewayAppSpec) -> GatewayAppCreated:
        """Create-or-lookup by a name derived from the application reference —
        ledger-driven re-runs must not duplicate. A 409 from a concurrent run
        is resolved by adopting the winner's application."""

    def subscribe(self, external_id: str, api_names: tuple[str, ...]) -> None:
        """API **names**, resolved to ids at call time. Already-held
        subscriptions are skipped, so a re-run adds nothing."""

    def map_keys(self, external_id: str, consumer_key: str, secret_ref: str) -> None:
        """Associates the Keycloak client with the WSO2 app. The one place a
        secret_ref is dereferenced — read transiently from the short-TTL cache
        in `integrations/secret_ref.py`, never stored or logged."""

    def unsubscribe(self, external_id: str, api_names: tuple[str, ...]) -> None:
        """Idempotent: never-subscribed or already-gone is success (B8)."""
```

- Errors → `AdapterError("WSO2", code, retryable)`; pagination handled where list APIs page.
- TLS verified everywhere (the legacy system disabled it); credentials from the secret store only.

### Verified in legacy source (2026-08-30)

| Claim                               | Evidence                                                                                                                                                                                                                         |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TLS was off for **every** WSO2 call | `SandboxConfiguration.restTemplateByPassSSL` builds a `TrustStrategy` returning `true` for any chain plus `NoopHostnameVerifier.INSTANCE`; `Wso2ServiceImpl` uses it for token, create-application, map-keys and subscribe alike |
| APIs were named by instance UUID    | `wso2.v3-subscription-api-list` is a comma-separated list of `apiId`s, split straight into the subscription request                                                                                                              |
| Nothing was ever unsubscribed       | `Wso2ServiceImpl` implements exactly four calls — token, add application, map keys, add subscription. There is no removal of any kind anywhere in the class                                                                      |
| Endpoints used                      | devportal **v2.1**: `/applications`, `/applications/{id}/map-keys`, `/subscriptions/multiple`, plus `/oauth2/token`                                                                                                              |

The last row is why `WSO2_DEVPORTAL_PATH` is a setting. We default to **v3**
(current), but the only evidence about NHA's actual deployment is that legacy
spoke v2.1 to it. One env var, and it must be confirmed on staging.

### Divergence: unsubscribe does not retire the application

An earlier draft had `unsubscribe` also delete the WSO2 application. It cannot:
the port takes `api_names`, so a partial unsubscribe is expressible, and
retiring the application on one API's removal would be wrong. Application
retirement is a distinct teardown step and belongs to [B8](B8-deprovisioning-chain.md),
which knows it is dismantling the whole thing.

## Acceptance criteria

- [x] Contract tests against a recording stub transport: create, subscribe, map-keys, unsubscribe — happy + error shapes (409 duplicate, 404 missing, 5xx, non-JSON body). Wire-level WireMock fixtures remain [B9](B9-wiremock-fault-injection-suite.md)'s.
- [x] Create/subscribe re-run safe: a second `create_application` makes no second app (asserted on the stub's create counter), an app created by a concurrent run is adopted, and re-subscribing adds nothing.
- [x] Unsubscribe idempotent — never-subscribed, and a subscription deleted underneath us, both succeed. TLS verification on: a test greps the whole `integrations` tree for a disabled-verification flag.
- [x] Retry/breaker inherited from [B1](B1-integration-ports-http-policy.md) and asserted (`5xx` retryable); admin read timeout 15s via `WSO2_READ_TIMEOUT_SECONDS`; no credential is logged (log-capture assertion) and none is persisted.
- [ ] Verified end-to-end against real sandbox-tier WSO2 from staging — **blocked on NHA**. There is no local WSO2 stand-in, so unlike [B3](B3-keycloak-adapter.md) nothing here has met a real server.
- [ ] **Rotate, then call an API.** `map_keys` hands WSO2 a copy of the Keycloak secret, but [C7](C7-credentials-panel.md)'s rotate only touches Keycloak — WSO2-side rotation is deferred to P4 by both tickets. That is safe *if* the integrator takes tokens from Keycloak and the gateway validates the JWT signature, leaving WSO2's copy merely stale. Inferred from the API shape, not observed. If it is wrong, every rotation silently breaks an integrator mid-testing, so this is the first thing to try on staging.

### Still owed by NHA

The **API names** to subscribe to. `WSO2_API_NAMES["SANDBOX"]` has no default
and `api_names_for()` raises `ImproperlyConfigured` when it is empty, so a
deployment must supply them. An empty default would have provisioned clients
that silently reach nothing — the failure this repo keeps finding in legacy.

## Out of scope (deferred)

`get_usage` milestone evidence (P4, flag-gated) · key rotation on WSO2 side · per-kind product sets beyond SANDBOX.
