# A6 — Reviews + quorum guard (`ADMIN_UNILATERAL` default, `N_OF_M` tested)

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review
> **Depends on** [A5](A5-workflow-state-machine.md)
> **Unblocks** [C5](C5-console-review-queue.md) (review actions + quorum indicator), approve→provisioning trigger ([B7](B7-provisioning-chain.md))
> **Refs** [01-backend.md §3.4](../01-backend.md) · [03-database.md §3.4](../03-database.md) · [00-master-plan.md §4](../00-master-plan.md)

## In plain words

Reviewers look at an application and record an opinion: approve, reject, or send back for fixes. This ticket stores those opinions as rows and answers one question for the approve button: **"is the bar met?"** The bar is configurable per environment — the pilot copies today's behaviour (an admin's decision alone is enough), but a stricter "N reviewers must agree" mode ships fully working, enabled by a single environment variable.

## Background

The legacy system recorded HTC reviewer opinions in fifteen wide-table columns keyed by JWT *username string* (`HTC1`…`HTC4`, `Admin`), and its 2-of-4 quorum checks were dead code — in practice a Super Admin approval alone triggered provisioning. v2 makes reviews **rows** and the quorum an explicit, environment-configurable guard on the approve transition.

**v0 defaults `WORKFLOW_QUORUM_POLICY=ADMIN_UNILATERAL`** — deliberate legacy behavioural parity for the pilot — but `N_OF_M` ships fully implemented and tested so flipping an env var is all a stricter environment needs.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `WorkflowReview` model + partial-unique migration | `sandbox/workflow/models.py` |
| 2 | `record_review()` service | `sandbox/workflow/services.py` |
| 3 | `QuorumPolicy` interface + both implementations, settings-selected | `sandbox/workflow/quorum.py` |
| 4 | Approve-guard wiring + `quorum_snapshot` freeze | `sandbox/workflow/machine.py` |
| 5 | Tally / "what's missing" selectors for [C5](C5-console-review-queue.md) | `sandbox/workflow/selectors.py` |
| 6 | Tests parametrised over both policies | `sandbox/workflow/tests/` |

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

### Service + quorum policy

```python
# workflow/services.py
def record_review(*, application, reviewer, decision, comment) -> WorkflowReview:
    """Application must be UNDER_REVIEW; reviewer permission required;
    upsert-within-round per the uniqueness rule; audited."""

# workflow/quorum.py — selected by settings.WORKFLOW_QUORUM_POLICY
class QuorumPolicy(Protocol):
    def is_satisfied(self, application, actor) -> bool: ...  # the approve guard
    def tally(self, application) -> dict: ...                # frozen into quorum_snapshot
```

| Policy | Approve guard passes when |
|---|---|
| `ADMIN_UNILATERAL` (v0 default) | actor holds the admin-approve permission — review tally irrelevant (legacy parity) |
| `N_OF_M` | ≥ N APPROVE rows from distinct authorised reviewers (N, M in settings) |

### Wiring

- Plug the policy into the approve guard in [A5](A5-workflow-state-machine.md)'s transition table; on approve, freeze `tally()` into `workflow_transition.quorum_snapshot` so history shows what satisfied the guard.
- REJECT/SEND_BACK paths: reject requires the same authority level; send-back returns the application to the applicant-editable state (SENT_BACK); comments ride on the review/transition rows.
- Selectors for [C5](C5-console-review-queue.md): review rows + tally + "what's missing for quorum".

## Acceptance criteria

- [ ] **Both policies fully tested**: `ADMIN_UNILATERAL` (admin approves with zero reviews; non-admin cannot) and `N_OF_M` (N−1 approvals → guard blocks; N → passes; duplicate reviewer counted once).
- [ ] Review uniqueness enforced per round; re-review after send-back works.
- [ ] `quorum_snapshot` present on every approve transition (asserted in tests).
- [ ] Authority via permissions/groups only.
- [ ] Switching policy via env var requires no code change (test parametrised over both settings).

## Out of scope (deferred)

Reviewer-assignment automation/routing · multi-stage review chains beyond the v0 graph · evidence gating (P4/P5).
