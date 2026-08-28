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

| # | Deliverable | Where |
|---|---|---|
| 1 | `State` choices + `WorkflowTransition`, `WorkflowAssignment` models | `sandbox/workflow/models.py` |
| 2 | `TRANSITIONS` table (data, introspectable) | `sandbox/workflow/machine.py` |
| 3 | `transition()` — the single state writer | `sandbox/workflow/services.py` |
| 4 | New `audit` app: `AuditEvent` model + `audit.emit()` helper | `sandbox/audit/` |
| 5 | Append-only enforcement migration (revoke UPDATE/DELETE) | `workflow`/`audit` migrations |
| 6 | History + queue selectors | `sandbox/workflow/selectors.py` |
| 7 | Tests: full legal + illegal transition table, atomicity, on-commit side-effects | `sandbox/workflow/tests/` |

### State machine + single entry point

```python
# workflow/models.py
class State(models.TextChoices):
    DRAFT, SUBMITTED, OTP_VERIFIED, UNDER_REVIEW,
    SANDBOX_APPROVED, PROVISIONING, PROVISIONED, PROVISIONING_FAILED,
    REJECTED, SENT_BACK,
    EXIT_REQUESTED, EXIT_REVIEW, PRODUCTION_APPROVED, EXIT_REJECTED, WITHDRAWN

# workflow/machine.py — the table is DATA: console and tests introspect it
# Spec = target state + guard callable + required Django permission + side-effect hooks
TRANSITIONS: dict[tuple[State, Action], Spec]

# workflow/services.py — the ONLY state writer in the system
def transition(application, action, actor, comment="") -> WorkflowTransition: ...
```

`transition()` runs one atomic block:

1. legal-transition check (illegal → `DomainError`),
2. guard (e.g. quorum satisfied — pluggable, [A6](A6-reviews-quorum.md)),
3. permission check (Django groups/permissions — **never username matching**),
4. append `workflow_transition` row,
5. update denormalized `Application.state` in the same transaction,
6. emit `audit_event`,
7. side-effects via `transaction.on_commit` (e.g. `SANDBOX_APPROVED` enqueues the provisioning chain; notification sends).

### Tables

`workflow_transition` — append-only history; **no UPDATE/DELETE grants for the app DB role** (enforced in a migration):

| Field | Type | Constraints / notes |
|---|---|---|
| `application` | FK → application | |
| `from_state` / `to_state` | char | CHECK: `(from_state, action, to_state)` ∈ legal graph |
| `action` | char | |
| `actor` | FK → user, null | null for system moves (e.g. chain completion) |
| `actor_role` | char | snapshot at transition time |
| `comment` | text | reviewer/admin comment |
| `quorum_snapshot` | JSONB, null | review tally frozen on approve ([A6](A6-reviews-quorum.md)) |
| `created_date` | datetime | append-only — no `modified_date`, no `deleted`; rows are immutable |

`audit_event` (new `audit` app) — append-only; replaces the legacy 3-call, content-free Kafka publisher (**no broker, no outbox**):

| Field | Type | Constraints / notes |
|---|---|---|
| `occurred_at` | datetime | BRIN index |
| `actor` | FK → user, null | |
| `action` | char | e.g. `application.approved` |
| `object_type` | char | polymorphic — deliberately FK-free toward domain objects |
| `object_external_id` | UUID | |
| `correlation_id` | char | ties web request ↔ Celery chain |
| `data` | JSONB | render-safe details — never secrets |

`workflow_assignment` is **not** in v0 — nothing writes or reads it here, and the legacy system has no assignment, claim, due-date or SLA concept to carry over. It arrives with reviewer routing in P3, when the requirements that decide its shape (claimed vs pushed, due per stage vs per application) actually exist.

Selectors: transition history per application; queue by state.

## Acceptance criteria

- [ ] Transition table 100% test-covered — **every legal and every illegal** (state, action) pair asserted.
- [ ] `transition()` is the only state writer (import-linter/review); views and shell move records identically.
- [ ] Every transition writes exactly one transition row + one audit event atomically (rollback test: guard failure leaves no rows).
- [ ] Append-only verified: UPDATE/DELETE as app role fails on transitions + audit.
- [ ] Side-effects fire on commit only (proven with `django_capture_on_commit_callbacks`).
- [ ] Authority = permissions, zero username strings; mypy/ruff clean.

## Out of scope (deferred)

Evidence-gating guard on milestone submission (conformance, P4/P5 — leave the guard point pluggable) · notification-centre IN_APP fan-out (P5).
