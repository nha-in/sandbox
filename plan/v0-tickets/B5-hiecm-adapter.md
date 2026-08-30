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
| 1 | `HiecmBridgeRegistry` implementing `BridgeRegistry` (create / status / deactivate) | `sandbox/integrations/hiecm/adapter.py` |
| 2 | Gateway session auth (cached, early refresh) via the B1 factory | same |
| 3 | Contract + fault-injection coverage (with [B9](B9-wiremock-fault-injection-suite.md)) | `sandbox/integrations/tests/test_hiecm.py` |
| 4 | Staging verification note: bridge active after provisioning, inactive after rejection | ticket PR |

Implements the `BridgeRegistry` protocol as [B1](B1-integration-ports-http-policy.md)
shipped it — DTOs in, no domain models:

```python
# integrations/hiecm/adapter.py — implements BridgeRegistry
class HiecmBridgeRegistry:
    def create_bridge(self, spec: BridgeSpec) -> BridgeCreated:
        """Registration is a PUT on the real gateway, so a ledger-driven re-run
        overwrites rather than duplicating. The bridge id is whatever it is
        given — this adapter derives nothing."""

    def get_bridge_status(self, bridge_id: str) -> BridgeStatus:
        """Typed status for B7's verification step and C7's polling partial."""

    def deactivate_bridge(self, bridge_id: str) -> None:
        """Idempotent (B8). Legacy had no such call at all."""
```

`update_bridge` from an earlier draft is **not** built: it is not on the port,
and no v0 flow changes a bridge URL after registration. `create_bridge` being a
PUT already covers correcting one.

- Auth per HIE-CM sandbox requirements (gateway session/token via the shared factory, cached with early refresh); errors → `AdapterError("HIECM", code, retryable)`.
- **Internal base URLs only** — the external URL rewrite (`/sandbox/v3/v1/*`) is IaC-owned, never in adapter config.

### Verified in legacy source (2026-08-30)

| Claim | Evidence |
|---|---|
| Bridge ids were the derivable client id | `WorkflowServiceImpl.addEntryToBridgeTable` does `bridge.setBridgeId(integratorClientId)`, and those ids were `SBXID_(sdId + 55)` — guessable, and publicly visible as bridge ids |
| Bridges were never deactivated | `HIECMGatewayFClient` declares exactly three calls — `findBridgeDetailsByBridgeId`, `addBridge`, `updateBridgeUrl`. The rejection path deletes only the Keycloak client |
| Registration was already a PUT | `@PutMapping(HIE_CM_GATEWAY_ADD_BRIDGE)` — upsert semantics, which is what makes re-run safety free rather than something we had to construct |
| **Every bridge pointed at a public request bin** | `SandboxConstant.BRIDGE_CALLBACK_URL = "https://webhook.site/0dde97cc-…"`, passed as the bridge `url` for every integrator (`WorkflowServiceImpl:288`) — not their own endpoint, and readable by anyone holding that link |

The last row was not in this ticket's original background and is worth raising
with NHA separately: if that bridge registry is still live, those entries still
point there.

### Judgement call: `blocklisted` folds into `active`

`BridgeStatus` carries one boolean, and the gateway reports `active` and
`blocklisted` separately. A blocklisted bridge moves no data, so reporting it as
active would tell [C7](C7-credentials-panel.md)'s panel the integrator is ready
when they are not. `get_bridge_status` therefore returns
`active and not blocklisted`. If blocklist handling ever needs to be surfaced on
its own — it is out of scope here — that wants a second field on the DTO rather
than unpicking this.

## Acceptance criteria

- [x] Contract tests against a recording stub transport: create, status, deactivate — happy + error shapes (missing bridge, 5xx, a body with no bridge object).
- [x] Create re-run safe (a second registration overwrites, and revives a deactivated bridge rather than duplicating it); deactivate idempotent for an unknown bridge and when repeated.
- [x] No external/rewritten URLs in adapter config — asserted, not just reviewed: a test rejects `/sandbox/` appearing in the configured base.
- [x] Timeouts/retry/breaker inherited from [B1](B1-integration-ports-http-policy.md); ABDM gateway headers asserted (`REQUEST-ID` a fresh UUID per call, `TIMESTAMP` in `GeneralUtils.TIMESTAMP_FORMAT`, `X-CM-ID`).
- [ ] Verified end-to-end against real sandbox-tier HIE-CM from staging — **blocked on NHA**. As with [B4](B4-wso2-adapter.md) there is no local stand-in, so nothing here has met a real gateway.

### Unverified guesses to settle on staging

- **The session endpoint.** Legacy passed the HIE-CM client a token obtained
  elsewhere rather than opening its own session, so `HIECM_SESSION_PATH` and the
  `{clientId, clientSecret} → {accessToken, expiresIn}` shape are convention, not
  evidence. If HIE-CM instead accepts a Keycloak-issued token, this collapses to
  reusing [B3](B3-keycloak-adapter.md)'s.
- **`REQUEST-ID` / `TIMESTAMP` header spellings** come from legacy's shared
  `ABDMConstant`, which is not in this repo; only `X-CM-ID` was spelled out.

## Out of scope (deferred)

Integrator callback registration + reachability probes (`applications_callback`, P4) · drift reconciliation of bridges (P4) · blocklist handling beyond surfacing status.
