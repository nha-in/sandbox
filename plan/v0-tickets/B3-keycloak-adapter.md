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
| 3 | Per-kind role-name sets in typed settings (SANDBOX only in v0) | `config/settings/base.py` + `keycloak/roles.py` |
| 4 | Contract + fault-injection coverage (with [B9](B9-wiremock-fault-injection-suite.md)) | `sandbox/integrations/tests/test_keycloak.py` |
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

### Verified against a real Keycloak (26.0, local realm — 2026-08-29)

Exercised end-to-end against `compose/local/keycloak/realm-abdm-sandbox.json`; these are measured, not assumed:

| Behaviour | Result |
|---|---|
| `GET /clients/{uuid}/client-secret`, twice | same value — safe to read |
| `POST /clients/{uuid}/client-secret` | rotates — the only call allowed in `rotate_client_secret` |
| `POST /clients/{uuid}/scope-mappings/realm` | 204 |
| `PUT /clients/{uuid}` with `enabled:false` | 204 |

**Granting a role takes two calls, not one.** Scope-mapping alone puts *nothing* in a `client_credentials` token — it only filters what may appear. The role must also be granted to the client's service-account user:

```
GET  /clients/{uuid}/service-account-user      -> {id}
POST /users/{id}/role-mappings/realm           <- [{id, name}, …]
```

With both, the integrator token carries exactly `["hip", "hiu"]`. With scope-mapping only, `realm_access.roles` is empty. **Legacy only ever scope-mapped** (`addRole`/`getAvailableRoles` are declared but never called), so legacy-issued tokens carry no ABDM realm roles at all — see the open question in [06-integrations.md](../06-integrations.md).

**Service account permissions** the provisioner needs (`realm-management` client roles): `manage-clients`, `view-clients`, `query-clients`, `view-realm` (role lookup by name), `manage-users` (grant to service accounts). `view-realm` and `manage-users` are not implied by the client permissions — both were 403s before being added.

**`fullScopeAllowed`** must be `false` on integrator clients (least privilege) but `true` on the provisioner itself, otherwise its own realm-management roles are stripped from its token and every Admin API call 403s.
- **GET vs POST distinction explicit and separately tested**: read ops must never call the rotating endpoint (the legacy system's exact bug).
- Errors → `AdapterError("KEYCLOAK", code, retryable)`; create is retry-safe only with a pre-check-by-client-id or idempotency guarantee (coordinated with the [B7](B7-provisioning-chain.md) ledger).
- `secret_ref` only where a system genuinely requires a copy (WSO2 `map_keys`, [B4](B4-wso2-adapter.md)).

## Acceptance criteria

- [x] Contract tests against a recording stub transport: create / roles-by-name / rotate / disable, happy + error shapes. Wire-level WireMock fixtures remain [B9](B9-wiremock-fault-injection-suite.md)'s job; the stub records requests, which is what the read-vs-rotate proof needs.
- [x] A test proves read paths never hit the rotate endpoint (`test_reading_the_secret_never_posts_to_the_rotate_endpoint`), and a live run confirms two reads return the same secret.
- [x] Role resolution: names → IDs at runtime; config contains role *names* only; only the configured SANDBOX set is assigned — a live token carried exactly `["healthId", "hip", "hiu"]` and nothing else.
- [x] client_id non-derivability tested (random 16 hex chars, no sequence component).
- [x] Secrets never logged or persisted (log-capture assertion over every record's message *and* attributes); `initial_secret`/`secret` are `repr=False`.
- [ ] Verified end-to-end against the real sandbox-tier Keycloak from staging — **blocked on NHA** (open question 4). Everything above was verified against the local realm.

### Still owed by NHA (open question 4)

The per-kind role subset. `KEYCLOAK_ROLE_NAMES["SANDBOX"]` currently defaults to
`healthId, hip, hiu, hfr` — chosen to track the v0 milestones (M1 ABHA, M2 HIP,
M3 HIU, M4 HPR/HFR), **not** confirmed by NHA. It is one env var
(`KEYCLOAK_SANDBOX_ROLE_NAMES`) and unknown names fail loudly at create time,
because roles are resolved by name against the live realm.

## Out of scope (deferred)

Per-kind role sets beyond SANDBOX (P2/P4) · IaC realm export (07 §6) · drift reconciliation (P4).
