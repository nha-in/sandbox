# A8 — Exit workflow + production approval

> **Lane** A — Backend: domain & workflow · **Phase** V0.4 Milestones, exit & pilot readiness
> **Depends on** [A5](A5-workflow-state-machine.md), [A6](A6-reviews-quorum.md), [A7](A7-declarations-uploads.md)
> **Unblocks** [C8](C8-milestone-exit-forms.md) (exit form), [C9](C9-playwright-e2e.md) (journey finale), pilot go/no-go
> **Refs** [01-backend.md §3.4](../01-backend.md) · [03-database.md §3.4](../03-database.md) · [06-integrations.md §4](../06-integrations.md)

## In plain words

The finish line. When an integrator believes they're ready for the real ABDM network, they submit an **exit request** with supporting documents. An admin reviews it and either approves — the application becomes *production-approved*, the pilot's happy ending — or rejects it with a reason, and the integrator can fix things and try again. This ticket adds those final moves to the workflow engine; the screens come in [C8](C8-milestone-exit-forms.md).

## Background

The sandbox journey ends with the integrator requesting **exit to production**: they submit an exit declaration with supporting documents, an admin reviews it, and approval marks the application `PRODUCTION_APPROVED` — the credential for entering the real ABDM ecosystem. In the legacy system, exit approval was Super Admin–only and one of only three events that were (uselessly) audited; v2 runs exit through the same state machine, service layer and audit trail as everything else.

> **Half-answered by [A7](A7-declarations-uploads.md); the rest still needs NHA** ([00-master-plan.md §10](../00-master-plan.md), open question 3): legacy exit is **scoped to a milestone set and repeatable** — `SdExit.integration_detail` holds `"M1,M2,M3"`, an integrator can have several exit rows, and the legacy UI picks the one matching the milestone track on screen. A7 has already taken the cheap half: an exit declaration records its own milestone set and carries its own `state`, and several exits per application are legal. What is left for this ticket is narrower — whether `PRODUCTION_APPROVED` stays a **terminal application state** when an integrator can be production-approved for M1 while still sandboxing M3. Decide that before wiring the transitions; the declaration model does not need to change either way.

The exit states (`EXIT_REQUESTED, EXIT_REVIEW, PRODUCTION_APPROVED, EXIT_REJECTED`) already exist in [A5](A5-workflow-state-machine.md)'s graph — this ticket implements their guards, services and side-effects.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Guards on the exit transitions (the edges themselves already ship in [A5](A5-workflow-state-machine.md)) | `sandbox/workflow/machine.py` |
| 2 | `request_exit()` service (declaration-bundle guard) | `sandbox/workflow/services.py` |
| 3 | **Settle the exit declaration** on approve/reject — see below | same |
| 4 | Notification side-effects on approve/reject | transition specs → [B6](B6-notification-adapter.md) `enqueue` |
| 5 | Exit-queue + exit-detail selectors for the console | `sandbox/workflow/selectors.py` |
| 6 | Tests: full path, reject + re-request loop, permission denials | `sandbox/workflow/tests/` |

### What A7 leaves for this ticket

- **`Declaration.state` has no writer yet.** A7 only ever writes `SUBMITTED`, so its guard against superseding a settled claim (`already_settled`) is currently inert. `approve_exit` must set the exit declaration to `APPROVED` and `reject_exit` to `REJECTED` — otherwise an integrator can resubmit over an exit that already reached production, silently retracting it. This is the single most important thing A8 owes A7.
- **Which declaration is being acted on**: the current one, i.e. the exit declaration holding unsuperseded claims. A7 ships `milestone_coverage(application)`; a `current_exit_declaration(application)` selector belongs here or in `declarations/selectors.py`.
- **`submit_exit_declaration` takes `milestones`** (not just payload + files), so the bundle guard checks claims rather than mere existence.
- **[A9](A9-seed-sandbox-demo.md)'s seed will break**: [`seed_sandbox_demo.py`](../../sandbox/catalog/management/commands/seed_sandbox_demo.py) drives `REQUEST_EXIT` with no exit declaration present. Seed the declaration in the same PR that adds the guard.

### Transitions (wired into [A5](A5-workflow-state-machine.md)'s table)

| From | Action | To | Actor / permission | Guard |
|---|---|---|---|---|
| `PROVISIONED` | `request_exit` | `EXIT_REQUESTED` | integrator (org member) | a current exit declaration exists with its documents ([A7](A7-declarations-uploads.md)); every milestone in that declaration's set must already hold a `MILESTONE` claim — which is what `milestone_coverage()` answers |
| `EXIT_REJECTED` | `request_exit` | `EXIT_REQUESTED` | integrator (org member) | same guard — the re-request edge already exists in the shipped machine |
| `EXIT_REQUESTED` | `start_exit_review` | `EXIT_REVIEW` | `workflow.review_application` | — |
| `EXIT_REVIEW` | `approve_exit` | `PRODUCTION_APPROVED` | `workflow.approve_application` | sets the declaration to `APPROVED` |
| `EXIT_REVIEW` | `reject_exit` | `EXIT_REJECTED` | `workflow.reject_application` | comment mandatory; sets the declaration to `REJECTED` |
| `EXIT_REVIEW` | `send_back_exit` | `PROVISIONED` | `workflow.review_application` | already in the shipped machine but absent from this table — decide whether it also settles the declaration |

**Re-request after rejection is a fresh exit declaration**, not a SENT_BACK-style edit — settled by A7. Submitting one supersedes the rejected declaration's claims in the same transaction, and the rejected declaration stays readable with its documents and reviewer comment. Nothing needs to release claims on rejection; the resubmission does it.

### Services

```python
# workflow/services.py (or applications/services/exit.py)
def request_exit(*, application, actor) -> None:
    """Validates the declaration bundle (A7), then
    transition(application, "request_exit", actor)."""

# approve_exit / reject_exit go through transition() directly, and additionally
# settle the exit declaration — the only writer of Declaration.state.
```

### Side-effects & surfaces

- Via `transaction.on_commit`: notification `production-approved` on approval; exit-rejected/sent-back email on rejection (template keys per [B6](B6-notification-adapter.md)).
- **Sandbox resources stay live on production approval in v0** (parity; deprovision-on-exit is main-plan P4) — but write the `ProvisionedResource` ledger note so ops know. Rejection of the *application* (not exit) is the deprovisioning trigger, handled by [B8](B8-deprovisioning-chain.md).
- Console surfaces: exit queue rows + approve/reject actions land in [C5](C5-console-review-queue.md)/[C8](C8-milestone-exit-forms.md); this ticket ships the selectors.

## Acceptance criteria

- [ ] Full exit path green in tests: request (guard passes/fails correctly) → review → approve → `PRODUCTION_APPROVED`, and the reject + re-request loop.
- [ ] Approval settles the exit declaration (`APPROVED`), and a later resubmission over it is refused with A7's `already_settled`.
- [ ] Exit approval requires the admin permission; integrator/reviewer roles cannot approve (matrix rows added).
- [ ] Every exit transition audited with actor + comment; approval freezes state history like any other transition.
- [ ] Approval/rejection notifications enqueued on commit (asserted).
- [ ] [A9](A9-seed-sandbox-demo.md)'s seed still reaches every exit state under the new guard.
- [ ] mypy/ruff clean; no view writes.

## Out of scope (deferred)

Deprovisioning on exit (main plan P4 — v0 deprovisions only on rejection) · conformance evidence gating of exit (P5) · public directory listing of production-approved orgs (P5).
