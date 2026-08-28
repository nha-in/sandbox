# 06 — Integrations: External System Adapters

**Parent:** [00-master-plan.md](00-master-plan.md) · **Audience:** backend engineers owning `integrations/` · **v0 tickets:** [B1–B9](v0-tickets/README.md)

---

## 1. In plain words

Approving an integrator means creating things in three systems we don't own: an identity **client** in Keycloak, an **application + subscriptions** in the WSO2 API gateway, and a **bridge** record in the HIE-CM registry (plus emails through a notification gateway). Talking to other people's systems is where software breaks: they hang, they error, they half-finish. So all of that lives behind one wall — the `integrations` app. Domain code talks to friendly Python interfaces ("ports"); the messy HTTP details live in "adapters" with strict time limits, careful retries, and circuit breakers. A **ledger table** records every resource we created in each system, so a crashed job can re-run and skip what's already done instead of creating duplicates — and so rejection can reliably un-create everything. For local dev, every port has a **fake**, so the whole portal runs on a laptop with no VPN.

## 2. Legacy findings

Six Feign clients with **zero timeouts, retries or breakers** — dependency hangs propagated into request threads. `getSecret` was bound to POST (every "read" **rotated** the secret). Realm-role UUIDs hardcoded in YAML; all 14 roles granted to every integrator. `Wso2FClient` didn't call WSO2 — it loopbacked into the service's own controller with SSL verification off. Provisioning ran synchronously with no idempotency (retry ⇒ duplicate clients/subscriptions). Rejection disabled only the Keycloak client — WSO2 apps and HIE-CM bridges stayed live. Gateway keys and two JWTs shipped in the frontend `.env`. A bespoke unauthenticated `hiu-service` acted as demo counterparty.

## 3. Design

```
sandbox/integrations/
├── ports.py              # Protocols: IdpAdmin, ApiGateway, BridgeRegistry, NotificationGateway (v0)
│                         #            LgdLookup, ReferenceEnv (v1)
├── http.py               # shared httpx factory: timeouts, retry, breaker, tracing
├── models.py             # ProvisionedResource ledger
├── fakes.py              # in-process fake per port (offline dev)
└── {keycloak,wso2,hiecm,notification}/adapter.py
```

- **Anti-corruption layer:** domain code imports ports/DTOs only (import-linter-enforced); never httpx, never external JSON shapes. Errors are always `AdapterError(system, code, retryable)`.
- **Shared client policy** (every adapter): explicit connect/read timeouts, tenacity retries on idempotent ops only, pybreaker per system, secret-store credentials with token caching, correlation-ID + `traceparent` headers, one structured log line per call. Full spec: [B1](v0-tickets/B1-integration-ports-http-policy.md).
- **Provisioning ledger** `integrations_provisioned_resource` — one row per (application, system), `UNIQUE` partial-indexed; the idempotency backstop for both chains and (v1) the anchor for drift reconciliation.
- **Chains as Celery, never in requests**; every step ledger-checked (skip if done), failure explicit (`PROVISIONING_FAILED` + console retry), all state moves via `workflow.transition()`.
- **Secret policy:** show-once + self-service rotation; nothing stored; GET-vs-rotate distinction explicit and tested.

## 4. v0 (POC)

The complete provisioning story ships in v0 — this is the pilot's critical path:

| Build | Ticket |
|---|---|
| Ports + shared http policy + ledger schema | [B1](v0-tickets/B1-integration-ports-http-policy.md) |
| Fake adapters for every port (offline dev) | [B2](v0-tickets/B2-fake-adapters.md) |
| Keycloak adapter: create/disable client, roles **by name at runtime**, rotate | [B3](v0-tickets/B3-keycloak-adapter.md) |
| WSO2 adapter: app create, subscribe, map-keys, unsubscribe | [B4](v0-tickets/B4-wso2-adapter.md) |
| HIE-CM adapter: bridge create/status/deactivate | [B5](v0-tickets/B5-hiecm-adapter.md) |
| Notification adapter + Celery send task + delivery log | [B6](v0-tickets/B6-notification-adapter.md) |
| Provisioning chain (Keycloak → WSO2 → HIE-CM) + `PROVISIONING_FAILED` + retry | [B7](v0-tickets/B7-provisioning-chain.md) |
| Deprovisioning chain on rejection (reverse order, all three systems) | [B8](v0-tickets/B8-deprovisioning-chain.md) |
| WireMock contract + fault-injection suite (incl. kill/retry idempotency proofs) | [B9](v0-tickets/B9-wiremock-fault-injection-suite.md) |

v0 notification templates: `send-otp`, `sandbox-approved`, `sandbox-rejected`, `exit-rejected`/`exit-sent-back`, `production-approved` — approval email links to the credentials panel, **never contains credentials**.

**Exit criteria (V0.3):** approval on staging provisions **real** credentials that obtain a token and call a sandbox API; kill-mid-chain/re-run proves no duplicates; rejection deprovisions all three systems.

## 5. v1 — everything else

| Item | Phase | Notes |
|---|---|---|
| Drift-reconciliation sweep (ledger vs external reality → `ORPHANED`/`FAILED` + alert) | P4 | anchored on the v0 ledger |
| Deprovision on exit/production approval | P4 | v0 deprovisions only on rejection |
| Callback registration + reachability probes (`applications_callback`) | P4 | strict timeouts, no retries on non-idempotent flow steps |
| WSO2 `get_usage(application, since)` milestone evidence (flag-gated) | P4 | feeds the review screen's evidence panel |
| `LgdLookup` adapter + daily Celery sync into catalog | P4 | v0 ships seeded LGD fixtures instead |
| **Reference environment** (`ReferenceEnv`): hosted ABDM-enabled Care HMIS instance (synthetic data, scheduled reset) + one-command local runner; portal ops = status, dataset reset | P4 | replaces the legacy hiu-service as demo counterparty |
| hiu-service decommission decision executed (preferred: demo-HIU logins become Keycloak users; deployable + DB deleted) | P4 | fallback: small authenticated adapter |
| Keycloak realm/roles-of-record via IaC export | P4/P6 | [07-infra-cicd.md](07-infra-cicd.md) §6 |

## 6. Definition of done

**v0**

- [ ] All v0 ports implemented; domain imports ports only (import-linter green).
- [ ] Every adapter: timeouts, retry, breaker, DTOs — proven by fault injection ([B9](v0-tickets/B9-wiremock-fault-injection-suite.md)).
- [ ] Both chains idempotent under kill/retry; failures visible + retryable in the console.
- [ ] Role assignment resolves names at runtime; zero instance UUIDs in config; no gateway credential outside the secret store.
- [ ] Fakes cover every port; `compose up && seed_sandbox_demo` ⇒ fully navigable portal offline.

**v1**

- [ ] Reconciliation sweep scheduled + alerting; `get_usage` verified against fixtures; reference instance reachable + reset-tested from the portal; hiu-service decision documented + executed.
