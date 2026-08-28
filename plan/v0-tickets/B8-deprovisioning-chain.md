# B8 — Deprovisioning chain (rejection path, all three systems)

> **Lane** B — Backend: integrations · **Phase** V0.3
> **Depends on** [B7](B7-provisioning-chain.md) (ledger + chain machinery), [B3](B3-keycloak-adapter.md)/[B4](B4-wso2-adapter.md)/[B5](B5-hiecm-adapter.md) disable ops
> **Unblocks** the V0.3 exit criterion ("rejection deprovisions all three systems"), [P6](P6-backup-restore-drill-and-pilot-runbook.md) runbook
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [03-database.md §3.4](../03-database.md)

## In plain words

The mirror image of provisioning: when a provisioned application is rejected, everything created for it must be switched **off** — the Keycloak client, the WSO2 subscription, *and* the HIE-CM bridge. The legacy system only disabled the first one, leaving rejected applicants with live gateway access indefinitely. Same ledger, same retry discipline, same "never silent" failure rules as [B7](B7-provisioning-chain.md), run in reverse.

## Background

**Verified legacy defect:** rejecting an integrator disabled only their Keycloak client — fire-and-forget — while the WSO2 application/subscriptions and the HIE-CM bridge stayed live indefinitely. Orphaned live resources for rejected applicants are a security hole, and v0 explicitly keeps the fix in scope rather than deferring it.

v2 runs the **reverse chain** over the provisioning ledger whenever an application with provisioned resources is rejected. (Exit/production-approval deprovisioning is main-plan P4; in v0 sandbox resources stay live after production approval — parity.)

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Reverse Celery chain: disable Keycloak → unsubscribe WSO2 → deactivate bridge | `sandbox/integrations/tasks.py` |
| 2 | Trigger wiring on `REJECTED` (+ any transition that strands ACTIVE ledger rows — document the set) | [A5](A5-workflow-state-machine.md) transition specs |
| 3 | Ledger flips `ACTIVE → DISABLED`; terminal failure → row `FAILED` + alert + console retry | chain |
| 4 | Sandbox token lifetime ≤15m verified/set + runbook note | Keycloak config + [P6](P6-backup-restore-drill-and-pilot-runbook.md) |
| 5 | `sandbox-rejected` notification wiring | [B6](B6-notification-adapter.md) |
| 6 | Tests vs fakes: full deprovision, kill/retry, already-disabled idempotency | `sandbox/integrations/tests/` |

### Chain behaviour

- **Trigger**: `REJECTED` transition ([A5](A5-workflow-state-machine.md)) on an application with ledger rows → enqueue the deprovisioning chain via `transaction.on_commit`. (Cover the state-graph reality: if rejection can only happen pre-provisioning in the v0 graph, wire the trigger to whichever transitions can strand ACTIVE ledger rows — e.g. withdrawal after provisioning — and document the covered set in the ticket PR.)
- **Reverse order**: disable Keycloak client → unsubscribe/retire WSO2 application → deactivate HIE-CM bridge. Each step:
  1. reads the ledger row; missing or already `DISABLED` → skip (idempotent);
  2. calls the adapter's disable/unsubscribe/deactivate op (each idempotent per [B3](B3-keycloak-adapter.md)/[B4](B4-wso2-adapter.md)/[B5](B5-hiecm-adapter.md));
  3. flips the row `ACTIVE → DISABLED` on success.
- **Same policies as provisioning**: retry with backoff (max 5/~30 min); terminal failure → visible failed state (row `FAILED` + admin alert + console retry using the same hook pattern as [B7](B7-provisioning-chain.md)) — never silent.
- **Revocation-latency note**: access is JWT-signature based, so revocation takes effect at token expiry. Verify/set sandbox token lifetime ≤15 min (Keycloak client/realm config) and document the lag in the [P6](P6-backup-restore-drill-and-pilot-runbook.md) runbook.
- Side-effects: `sandbox-rejected` notification ([B6](B6-notification-adapter.md)); every step audited with correlation ID.

## Acceptance criteria

- [ ] Rejection of a provisioned application flips all three ledger rows to DISABLED and disables the resources (fakes in CI; verified against real systems on staging).
- [ ] Kill mid-chain, re-run ⇒ remaining steps only, no errors on already-disabled resources ([B9](B9-wiremock-fault-injection-suite.md) fault-injection version).
- [ ] Terminal failure visible (row FAILED + alert) and manually retryable from the console.
- [ ] Rejected integrator's credentials stop working within the token lifetime (staging check); lifetime ≤15m confirmed.
- [ ] Chain enqueued on commit; all transitions audited.

## Out of scope (deferred)

Deprovision on exit/production approval (P4) · drift-reconciliation sweep marking ORPHANED (P4) · re-provisioning a previously rejected org (new application → new resources via [B7](B7-provisioning-chain.md)).
