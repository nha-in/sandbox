# A6 — Reviews + admin approve guard

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review
> **Depends on** [A5](A5-workflow-state-machine.md)
> **Unblocks** [C5](C5-console-review-queue.md) (review actions + tally display), approve→provisioning trigger ([B7](B7-provisioning-chain.md))
> **Refs** [01-backend.md §3.4](../01-backend.md) · [03-database.md §3.4](../03-database.md) · [00-master-plan.md §4](../00-master-plan.md)

## In plain words

Reviewers look at an application and record an opinion: approve, reject, or send back for fixes. This ticket stores those opinions as rows. The opinions are **advisory** — an admin's decision is what actually moves the application, which is exactly how the system behaves today.

## Background

The legacy system recorded HTC reviewer opinions in fifteen wide-table columns keyed by JWT _username string_ (`HTC1`…`HTC4`, `Admin`), and its 2-of-4 quorum checks were dead code — in practice a Super Admin approval alone triggered provisioning. v2 makes reviews **rows** and the approve guard an explicit permission check.

**Approval requires the admin-approve permission and nothing else** — deliberate parity with real legacy behaviour. There is no configurable quorum policy: an unused abstraction plus an environment variable nobody will change is more machinery than the rule deserves. If NHA later want "N reviewers must agree", it is a guard function and a test, and the review rows needed to evaluate it are already being written.

## What to build

### Deliverables

| #   | Deliverable                                          | Where                           |
| --- | ---------------------------------------------------- | ------------------------------- |
| 1   | `WorkflowReview` model + partial-unique migration    | `sandbox/workflow/models.py`    |
| 2   | `record_review()` service                            | `sandbox/workflow/services.py`  |
| 3   | Approve-guard wiring (admin permission)              | `sandbox/workflow/machine.py`   |
| 4   | Tally selectors for [C5](C5-console-review-queue.md) | `sandbox/workflow/selectors.py` |
| 5   | Tests: authority, rounds, tally                      | `sandbox/workflow/tests/`       |

### `workflow_review`

| Field         | Type             | Constraints / notes                                                      |
| ------------- | ---------------- | ------------------------------------------------------------------------ |
| `application` | FK → application |                                                                          |
| `reviewer`    | FK → user        |                                                                          |
| `round`       | int              | increments when the application re-enters review after a send-back       |
| `decision`    | char + CHECK     | `APPROVE \| REJECT \| SEND_BACK`                                         |
| `comment`     | text             | the single home for reviewer/admin comment text — never copied elsewhere |
| `decided_at`  | datetime         |                                                                          |
| —             |                  | `UNIQUE (application, reviewer, round) WHERE deleted = false`            |

A send-back/re-submission opens a new round by incrementing `round`; earlier rows stay visible and queryable rather than being soft-deleted, so the console timeline can show what each round said without reaching past the default manager.

### Service + approve guard

```python
# workflow/services.py
def record_review(*, application, reviewer, decision, comment) -> WorkflowReview:
    """Application must be SUBMITTED; reviewer permission required;
    upsert within the current round per the uniqueness rule; audited."""
```

The approve guard in [A5](A5-workflow-state-machine.md)'s transition table is a permission check: the actor must hold the admin-approve permission. Review rows do not gate it — they inform the human making the call, and the console shows the tally beside the button.

### Wiring

- REJECT/SEND_BACK paths: reject requires the same authority level; send-back returns the application to the applicant-editable state (SENT_BACK) and increments the review round.
- Selectors for [C5](C5-console-review-queue.md): review rows for the current round + tally.

## Acceptance criteria

- [x] Admin approves with zero reviews recorded; a non-admin holding only the review permission cannot approve (both asserted).
- [x] Review uniqueness enforced per `(application, reviewer, round)`; re-review after send-back opens a new round and leaves the previous round readable.
- [x] Comments live only on review rows — no copy on the transition (asserted, and enforced by [A5](A5-workflow-state-machine.md)'s `review_driven` rule, which raises `DomainError(code="comment_not_allowed")`).
- [x] Authority via permissions/groups only, zero username strings.

### `round` is derived, not stored

There is no `round` counter on the application. The current round is
`1 + the number of SEND_BACK transitions`, read from A5's append-only log
(`selectors.current_round`). A stored counter is a second source of truth that
can drift from the history; a derived one cannot. It also means a send-back
recorded by any path — console, shell, future automation — opens the next round
without anyone remembering to increment anything.

### `record_review()` does not move the application

Reviews are advisory, so the service records the opinion and audits it, and
nothing else. The admin's separate `transition()` call is what moves state.
[C5](C5-console-review-queue.md) will do both inside one atomic view action.
Keeping them apart is what makes "admin approves with zero reviews" work, which
is the real legacy behaviour this ticket deliberately preserves.

### Re-review within a round updates, across rounds appends

`update_or_create` on `(application, reviewer, round)`: a reviewer changing
their mind in round 1 edits their row rather than adding a second one, while
round 2 gets a fresh row and round 1 stays readable and un-deleted.

## Out of scope (deferred)

Reviewer-assignment automation/routing · multi-stage review chains beyond the v0 graph · evidence gating (P4/P5).
