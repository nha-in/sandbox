# B3 — Keycloak adapter (`IdpAdmin`): client lifecycle, runtime role resolution, rotate

> **Lane** B — Backend: integrations · **Phase** V0.3
> **Depends on** [B1](B1-integration-ports-http-policy.md) · **real sandbox-tier Keycloak service account** (requested in V0.1 — confirm access before starting)
> **Unblocks** [B7](B7-provisioning-chain.md), [B8](B8-deprovisioning-chain.md), [C7](C7-credentials-panel.md) (rotate)
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [05-security.md §3.1/§3.3](../05-security.md)

## In plain words

Keycloak is the identity server that mints the **client id + secret** an integrator's software uses to call ABDM — the actual product the sandbox hands out. This connector creates that client when an application is approved, assigns it only the permissions its kind needs, rotates its secret on request, and disables it on rejection. Hard rules: reading must never accidentally rotate (the legacy system's bug), IDs must not be guessable, and the secret is passed along exactly once — we never keep a copy.

## Background

Keycloak's scope in v2 is **integrator machine credentials only** — portal login is allauth-local, so a Keycloak outage degrades credential management, never portal access. The integrator's client id/secret issued here is what WSO2 and HIE-CM validate at runtime; it is the product the whole sandbox exists to hand out.

Legacy pitfalls this adapter must design against (all verified in source):
- `getSecret` was Feign-bound to **POST — every "read" rotated the secret**;
- realm-role **UUIDs and containerIds hardcoded in YAML** (instance-coupled config);
- all 14 realm roles granted to every integrator regardless of kind;
- client IDs derivable (`SBXID_(sdId+55)`) and publicly visible as bridge IDs;
- plaintext secret copies stored in the DB (`sd_status.gen_securate`) and emailed.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `KeycloakIdpAdmin` implementing `IdpAdmin` (create / roles-by-name / rotate / disable) | `sandbox/integrations/keycloak/adapter.py` |
| 2 | Service-account token handling (cache + early refresh) via the B1 factory | same |
| 3 | Per-kind role-name sets in typed settings (SANDBOX only in v0) | `config/settings/*` |
| 4 | Contract + fault-injection coverage (with [B9](B9-wiremock-fault-injection-suite.md)) | `tests/integrations/keycloak/` |
| 5 | Staging verification note: real client created/rotated/disabled | ticket PR |

Implements `IdpAdmin` over the Keycloak Admin REST API using the [B1](B1-integration-ports-http-policy.md) http factory:

```python
# integrations/keycloak/adapter.py — implements IdpAdmin
class KeycloakIdpAdmin:
    def create_client(self, application: Application) -> ClientCreated:
        """Non-derivable client_id (random component — never sequence-derived).
        Returns ClientCreated(client_id, external_id, initial_secret).
        initial_secret is returned ONCE → show-once flow (C7);
        never persisted by us, never logged."""

    def rotate_client_secret(self, external_id: str) -> SecretRotated:
        """Keycloak POST /client-secret — the ONLY code path allowed to hit
        that endpoint. New secret returned once."""

    def disable_client(self, external_id: str) -> None:
        """Idempotent: disabling a disabled/missing client is success (B8)."""
```

- **Role scope mappings resolved by *name* at runtime** — look up role IDs via the Admin API at call time; role-name sets configured **per application kind** (v0: the SANDBOX set only — least privilege). Zero instance UUIDs anywhere in config.
- **GET vs POST distinction explicit and separately tested**: read ops must never call the rotating endpoint (the legacy system's exact bug).
- Errors → `AdapterError("KEYCLOAK", code, retryable)`; create is retry-safe only with a pre-check-by-client-id or idempotency guarantee (coordinated with the [B7](B7-provisioning-chain.md) ledger).
- `secret_ref` only where a system genuinely requires a copy (WSO2 `map_keys`, [B4](B4-wso2-adapter.md)).

## Acceptance criteria

- [ ] Contract tests against WireMock fixtures ([B9](B9-wiremock-fault-injection-suite.md)): create / roles-by-name / rotate / disable, happy + error shapes.
- [ ] A test proves read paths never hit the rotate endpoint (fixture fails the suite if POST `/client-secret` is called by a read).
- [ ] Role resolution: names → IDs at runtime; config contains role *names* only (checked in config review); only the SANDBOX role set assigned.
- [ ] client_id non-derivability tested (no sequential/derivable component).
- [ ] Secrets never logged or persisted (log-capture assertion + schema review); timeouts/retry/breaker verified via fault injection.
- [ ] Verified end-to-end against the real sandbox-tier Keycloak from staging.

## Out of scope (deferred)

Per-kind role sets beyond SANDBOX (P2/P4) · IaC realm export (07 §6) · drift reconciliation (P4).
