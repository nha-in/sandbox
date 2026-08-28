# A8 — Exit workflow + production approval

> **Lane** A — Backend: domain & workflow · **Phase** V0.4 Milestones, exit & pilot readiness
> **Depends on** [A5](A5-workflow-state-machine.md), [A6](A6-reviews-quorum.md), [A7](A7-declarations-uploads.md)
> **Unblocks** [C8](C8-milestone-exit-forms.md) (exit form), [C9](C9-playwright-e2e.md) (journey finale), pilot go/no-go
> **Refs** [01-backend.md §3.4](../01-backend.md) · [03-database.md §3.4](../03-database.md) · [06-integrations.md §4](../06-integrations.md)

## In plain words

The finish line. When an integrator believes they're ready for the real ABDM network, they submit an **exit request** with supporting documents. An admin reviews it and either approves — the application becomes *production-approved*, the pilot's happy ending — or rejects it with a reason, and the integrator can fix things and try again. This ticket adds those final moves to the workflow engine; the screens come in [C8](C8-milestone-exit-forms.md).

## Background

The sandbox journey ends with the integrator requesting **exit to production**: they submit an exit declaration with supporting documents, an admin reviews it, and approval marks the application `PRODUCTION_APPROVED` — the credential for entering the real ABDM ecosystem. In the legacy system, exit approval was Super Admin–only and one of only three events that were (uselessly) audited; v2 runs exit through the same state machine, service layer and audit trail as everything else.

The exit states (`EXIT_REQUESTED, EXIT_REVIEW, PRODUCTION_APPROVED, EXIT_REJECTED`) already exist in [A5](A5-workflow-state-machine.md)'s graph — this ticket implements their guards, services and side-effects.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Exit transitions + guards wired into the table | `sandbox/workflow/machine.py` |
| 2 | `request_exit()` service (declaration-bundle guard) | `sandbox/workflow/services.py` |
| 3 | Notification side-effects on approve/reject | transition specs → [B6](B6-notification-adapter.md) `enqueue` |
| 4 | Exit-queue + exit-detail selectors for the console | `sandbox/workflow/selectors.py` |
| 5 | Tests: full path, reject + re-request loop, permission denials | `sandbox/workflow/tests/` |

### Transitions (wired into [A5](A5-workflow-state-machine.md)'s table)

| From | Action | To | Actor / permission | Guard |
|---|---|---|---|---|
| `PROVISIONED` | `request_exit` | `EXIT_REQUESTED` | integrator (org member) | exit declaration + required documents exist ([A7](A7-declarations-uploads.md)); milestone prerequisite — define it (all active milestones declared, or explicitly none) and record the choice in the ticket PR |
| `EXIT_REQUESTED` | `start_exit_review` | `EXIT_REVIEW` | staff pickup, or automatic on request — decide and document | — |
| `EXIT_REVIEW` | `approve_exit` | `PRODUCTION_APPROVED` | admin permission (legacy parity: Super Admin–level) | — |
| `EXIT_REVIEW` | `reject_exit` | `EXIT_REJECTED` | admin permission | comment mandatory |

Re-request after rejection is allowed — document whether via SENT_BACK-style edit or a fresh exit declaration.

### Services

```python
# workflow/services.py (or applications/services/exit.py)
def request_exit(*, application, actor) -> None:
    """Validates the declaration bundle (A7), then
    transition(application, "request_exit", actor)."""

# approve_exit / reject_exit go through transition() directly — no bespoke write path
```

### Side-effects & surfaces

- Via `transaction.on_commit`: notification `production-approved` on approval; exit-rejected/sent-back email on rejection (template keys per [B6](B6-notification-adapter.md)).
- **Sandbox resources stay live on production approval in v0** (parity; deprovision-on-exit is main-plan P4) — but write the `ProvisionedResource` ledger note so ops know. Rejection of the *application* (not exit) is the deprovisioning trigger, handled by [B8](B8-deprovisioning-chain.md).
- Console surfaces: exit queue rows + approve/reject actions land in [C5](C5-console-review-queue.md)/[C8](C8-milestone-exit-forms.md); this ticket ships the selectors.

## Acceptance criteria

- [ ] Full exit path green in tests: request (guard passes/fails correctly) → review → approve → `PRODUCTION_APPROVED`, and the reject + re-request loop.
- [ ] Exit approval requires the admin permission; integrator/reviewer roles cannot approve (matrix rows added).
- [ ] Every exit transition audited with actor + comment; approval freezes state history like any other transition.
- [ ] Approval/rejection notifications enqueued on commit (asserted).
- [ ] mypy/ruff clean; no view writes.

## Out of scope (deferred)

Deprovisioning on exit (main plan P4 — v0 deprovisions only on rejection) · conformance evidence gating of exit (P5) · public directory listing of production-approved orgs (P5).
