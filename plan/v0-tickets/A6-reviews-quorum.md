# A6 — Reviews + admin approve guard

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review
> **Depends on** [A5](A5-workflow-state-machine.md)
> **Unblocks** [C5](C5-console-review-queue.md) (review actions + tally display), approve→provisioning trigger ([B7](B7-provisioning-chain.md))
> **Refs** [01-backend.md §3.4](../01-backend.md) · [03-database.md §3.4](../03-database.md) · [00-master-plan.md §4](../00-master-plan.md)

## In plain words

Reviewers look at an application and record an opinion: approve, reject, or send back for fixes. This ticket stores those opinions as rows. The opinions are **advisory** — an admin's decision is what actually moves the application, which is exactly how the system behaves today.

## Background

The legacy system recorded HTC reviewer opinions in fifteen wide-table columns keyed by JWT *username string* (`HTC1`…`HTC4`, `Admin`), and its 2-of-4 quorum checks were dead code — in practice a Super Admin approval alone triggered provisioning. v2 makes reviews **rows** and the approve guard an explicit permission check.

**Approval requires the admin-approve permission and nothing else** — deliberate parity with real legacy behaviour. There is no configurable quorum policy: an unused abstraction plus an environment variable nobody will change is more machinery than the rule deserves. If NHA later want "N reviewers must agree", it is a guard function and a test, and the review rows needed to evaluate it are already being written.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `WorkflowReview` model + partial-unique migration | `sandbox/workflow/models.py` |
| 2 | `record_review()` service | `sandbox/workflow/services.py` |
| 3 | Approve-guard wiring (admin permission) | `sandbox/workflow/machine.py` |
| 4 | Tally selectors for [C5](C5-console-review-queue.md) | `sandbox/workflow/selectors.py` |
| 5 | Tests: authority, rounds, tally | `sandbox/workflow/tests/` |

### `workflow_review`

| Field | Type | Constraints / notes |
|---|---|---|
| `application` | FK → application | |
| `reviewer` | FK → user | |
| `round` | int | increments when the application re-enters review after a send-back |
| `decision` | char + CHECK | `APPROVE \| REJECT \| SEND_BACK` |
| `comment` | text | the single home for reviewer/admin comment text — never copied elsewhere |
| `decided_at` | datetime | |
| — | | `UNIQUE (application, reviewer, round) WHERE deleted = false` |

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

- [ ] Admin approves with zero reviews recorded; a non-admin holding only the review permission cannot approve (both asserted).
- [ ] Review uniqueness enforced per `(application, reviewer, round)`; re-review after send-back opens a new round and leaves the previous round readable.
- [ ] Comments live only on review rows — no copy on the transition (asserted).
- [ ] Authority via permissions/groups only, zero username strings.

## Out of scope (deferred)

Reviewer-assignment automation/routing · multi-stage review chains beyond the v0 graph · evidence gating (P4/P5).
