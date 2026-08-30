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

- [x] Withdrawal of a provisioned application flips all three ledger rows to DISABLED and disables the resources (fakes in CI).
- [x] Kill mid-chain, re-run ⇒ remaining steps only, no errors on already-disabled resources ([B9](B9-adapter-resilience-suite.md) proves the same from the request journal).
- [x] Terminal failure visible (row FAILED + Sentry) and manually retryable from the console.
- [x] Chain enqueued on commit; retries audited.
- [ ] Rejected integrator's credentials stop working within the token lifetime; lifetime ≤15m confirmed — **staging, blocked on NHA**. Deliverable 4 (token lifetime + [P6](P6-backup-restore-drill-and-pilot-runbook.md) runbook note) is not done.

### The covered set

Ledger rows only exist from `PROVISIONING` onward, so the trigger belongs on every
edge that leaves those states for a terminal one:

| Edge | Why |
| --- | --- |
| `SUBMITTED → REJECT` | No rows exist yet — `REJECT` is only legal from `SUBMITTED`. Wired anyway, and a no-op, so the wiring survives any future edge that makes rejection reachable later. |
| `PROVISIONED → WITHDRAW` | The path the ticket anticipated. |
| `PROVISIONING_FAILED → WITHDRAW` | **Added by this ticket.** `RETRY_PROVISIONING` was the only move out of `PROVISIONING_FAILED`, so an applicant whose chain failed for good was stuck forever *beside the partial resources it had already created* — a Keycloak client and possibly a WSO2 subscription, live, with no reachable state that would ever tear them down. |

Not covered, deliberately: `PRODUCTION_APPROVED` and `EXIT_REJECTED` both leave
sandbox resources live on purpose (P4 owns exit deprovisioning), and
`PROVISIONING` itself can only move to `PROVISIONED` or `PROVISIONING_FAILED`,
both of which are covered above.

### Decisions worth knowing

- **Teardown does not stop at the first failure; provisioning does.** Building a
  bridge for a client that does not exist is pointless, so [B7](B7-provisioning-chain.md)
  halts. Leaving a bridge switched on because Keycloak happened to be down is a
  live credential for a departed integrator, so this chain records the failed row
  and carries on to the next system.
- **A FAILED row is retried, not skipped.** The step acts on `ACTIVE` and
  `FAILED` and skips `DISABLED` and missing. The first draft skipped anything
  that was not `ACTIVE`, which meant a failed teardown could never be retried —
  caught by the console-retry test.
- **`retry_deprovisioning` is not a transition.** The application is already
  terminal, so there is no legal move to hang it on; the permission check
  (`workflow.retry_provisioning`) and the audit row are made explicitly instead
  of being inherited from `transition()`.
- **WSO2 unsubscribes from `api_names_for(kind)`** — the same source provisioning
  subscribed from, not a record of what was actually subscribed. If the
  configured set changes between provision and teardown, the difference is left
  for P4's sweep rather than guessed at.

## Out of scope (deferred)

Deprovision on exit/production approval (P4) · drift-reconciliation sweep marking ORPHANED (P4) · re-provisioning a previously rejected org (new application → new resources via [B7](B7-provisioning-chain.md)).
