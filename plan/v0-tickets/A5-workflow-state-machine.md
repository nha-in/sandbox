# A5 — Workflow state machine + `transition()` service + audit events

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review
> **Depends on** [A3](A3-applications-model.md)
> **Unblocks** [A6](A6-reviews-quorum.md), [A8](A8-exit-workflow.md), [B7](B7-provisioning-chain.md)/[B8](B8-deprovisioning-chain.md) (chains fire off transitions), [C5](C5-console-review-queue.md), [C6](C6-integrator-dashboard.md)
> **Refs** [01-backend.md §3.4](../01-backend.md) · [03-database.md §3.4](../03-database.md)

## In plain words

An application moves through a fixed pipeline of states — draft, submitted, under review, approved, provisioned, …, production-approved. This ticket builds the engine that owns those moves: a single function, `transition()`, which is the **only** code in the system allowed to change an application's state. It checks the move is legal, checks the person is allowed to make it, records it in a tamper-proof history, and writes an audit trail — all or nothing. Every button, admin screen and background job goes through it, so nothing can ever move an application "off the books".

## Background

The legacy workflow was magic status integers (0–5, 9–11) in native SQL, an 849-line `WorkflowServiceImpl` with swallow-all catches, per-reviewer columns on a wide `SdStatus` table, and **no audit** of approvals, provisioning or logins. Verified legacy facts to design against: HTC reviews unordered, the 2-of-4 quorum helpers are dead code, provisioning fires on Super Admin approval alone, exit approval is Super Admin–only, reviewer identity is a JWT username string.

v2 replaces all of that with an explicit, audited state machine with **exactly one write path**. This ticket is the heart of the backend: everything downstream (reviews, provisioning, console, dashboard) hangs off `transition()`.

## What to build

### Deliverables

| #   | Deliverable                                                                                                              | Where                           |
| --- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------- |
| 1   | `WorkflowTransition` model (`State` choices already live on `applications.Application` — [A3](A3-applications-model.md)) | `sandbox/workflow/models.py`    |
| 2   | `TRANSITIONS` table (data, introspectable)                                                                               | `sandbox/workflow/machine.py`   |
| 3   | `transition()` — the single state writer                                                                                 | `sandbox/workflow/services.py`  |
| 4   | New `audit` app: `AuditEvent` model + `audit.emit()` helper                                                              | `sandbox/audit/`                |
| 5   | Append-only enforcement migration (revoke UPDATE/DELETE)                                                                 | `workflow`/`audit` migrations   |
| 6   | History + queue selectors                                                                                                | `sandbox/workflow/selectors.py` |
| 7   | Tests: full legal + illegal transition table, atomicity, on-commit side-effects                                          | `sandbox/workflow/tests/`       |

### State machine + single entry point

```python
# applications/models.py (A3) — workflow FKs to applications, never the
# reverse, so the enum lives here; workflow imports it rather than redefining it
class ApplicationState(models.TextChoices):
    DRAFT, SUBMITTED,
    SANDBOX_APPROVED, PROVISIONING, PROVISIONED, PROVISIONING_FAILED,
    REJECTED, SENT_BACK,
    EXIT_REQUESTED, EXIT_REVIEW, PRODUCTION_APPROVED, EXIT_REJECTED, WITHDRAWN

# workflow/machine.py — the table is DATA: console and tests introspect it
# Spec = target state + guard callable + required Django permission + side-effect hooks
TRANSITIONS: dict[tuple[ApplicationState, Action], Spec]

# workflow/services.py — the ONLY state writer in the system
def transition(application, action, actor, comment="") -> WorkflowTransition: ...
```

`transition()` runs one atomic block:

1. legal-transition check (illegal → `DomainError`),
2. guard (per-action checks, e.g. the exit milestone prerequisite — [A8](A8-exit-workflow.md)),
3. permission check (Django groups/permissions — **never username matching**),
4. append `workflow_transition` row,
5. update denormalized `Application.state` in the same transaction,
6. emit `audit_event`,
7. side-effects via `transaction.on_commit` (e.g. `SANDBOX_APPROVED` enqueues the provisioning chain; notification sends).

### Tables

`workflow_transition` — append-only history; **no UPDATE/DELETE grants for the app DB role** (enforced in a migration):

| Field                     | Type             | Constraints / notes                                                                                                          |
| ------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `application`             | FK → application |                                                                                                                              |
| `from_state` / `to_state` | char             | CHECK: `(from_state, action, to_state)` ∈ legal graph                                                                        |
| `action`                  | char             |                                                                                                                              |
| `actor`                   | FK → user, null  | null for system moves (e.g. chain completion)                                                                                |
| `comment`                 | text             | only for moves with no review behind them (withdraw, system notes); review-driven moves keep their comment on the review row |
| `created_date`            | datetime         | append-only — no `modified_date`, no `deleted`; rows are immutable                                                           |

`audit_event` (new `audit` app) — append-only; replaces the legacy 3-call, content-free Kafka publisher (**no broker, no outbox**):

| Field                | Type            | Constraints / notes                                      |
| -------------------- | --------------- | -------------------------------------------------------- |
| `occurred_at`        | datetime        | BRIN index                                               |
| `actor`              | FK → user, null |                                                          |
| `action`             | char            | e.g. `application.approved`                              |
| `object_type`        | char            | polymorphic — deliberately FK-free toward domain objects |
| `object_external_id` | UUID            |                                                          |
| `correlation_id`     | char            | ties web request ↔ Celery chain                          |
| `data`               | JSONB           | render-safe details — never secrets                      |

`workflow_assignment` is **not** in v0 — nothing writes or reads it here, and the legacy system has no assignment, claim, due-date or SLA concept to carry over. It arrives with reviewer routing in P3, when the requirements that decide its shape (claimed vs pushed, due per stage vs per application) actually exist.

Selectors: transition history per application; queue by state.

## Acceptance criteria

- [x] Transition table 100% test-covered — **every legal and every illegal** (state, action) pair asserted (13 states × 14 actions = 182 pairs, 20 legal).
- [x] `transition()` is the only state writer (import-linter/review); views and shell move records identically.
- [x] Every transition writes exactly one transition row + one audit event atomically (rollback test: guard failure leaves no rows).
- [x] Append-only verified: UPDATE/DELETE as a non-superuser role fails on transitions + audit — **see the caveat below**.
- [x] Side-effects fire on commit only (proven with `django_capture_on_commit_callbacks`).
- [x] Authority = permissions, zero username strings; mypy/ruff clean.

### Append-only only holds if the app role is not a superuser

The migrations `REVOKE UPDATE, DELETE ... FROM CURRENT_USER`, which is correct
SQL — but PostgreSQL skips every privilege check for a superuser, and the local
and CI databases hand the app the image's superuser account. The revoke is
therefore **inert in local and CI**, and the tests prove the mechanism against a
purpose-made non-superuser role instead of pretending otherwise.

`tests/test_append_only.py` also asserts that the local role _is_ a superuser, so
the day that stops being true the test fails and the caveat gets revisited
deliberately rather than by accident.

**Deployment requirement** ([07-infra-cicd.md](../07-infra-cicd.md)): staging and
production must connect as a non-superuser role that does not own these tables.
Without that, the append-only guarantee is decorative.

### Hook registry rather than direct chain calls

`Spec.hooks` names side effects (`provisioning_chain`, `deprovisioning_chain`,
the `notify_*` set); [B7](B7-provisioning-chain.md)/[B8](B8-deprovisioning-chain.md)/[B6](B6-notification-adapter.md)
register handlers with `services.register_hook()`. An unregistered name is a
no-op, which is what lets A5 ship and be exercised before any of them exist —
and keeps `workflow` free of imports into `integrations`.

### Exit edges are provisional

`REQUEST_EXIT` / `START_EXIT_REVIEW` / `APPROVE_EXIT` / `REJECT_EXIT` /
`SEND_BACK_EXIT` are implemented against the single-exit reading of the graph. If
[00-master-plan.md §10](../00-master-plan.md) open question 3 resolves to
"repeatable per milestone track", [A8](A8-exit-workflow.md) replaces these edges
with a scoped record. Nothing else in v0 depends on their shape.

### `WITHDRAW` from `PROVISIONED` is the v0 deprovisioning trigger

[B8](B8-deprovisioning-chain.md) asks for "whichever transitions can strand
ACTIVE ledger rows". Rejection is only legal from `SUBMITTED` — before anything
is provisioned — so the transition that actually strands resources is withdrawal
after provisioning. Both carry the `deprovisioning_chain` hook.

## Out of scope (deferred)

Evidence-gating guard on milestone submission (conformance, P4/P5 — leave the guard point pluggable) · notification-centre IN_APP fan-out (P5).
