# C5 — Console: review queue + application detail + review actions

> **Lane** C — Full-stack UI · **Phase** V0.2 Apply & review
> **Depends on** [A5](A5-workflow-state-machine.md), [A6](A6-reviews-quorum.md) (services/selectors) · V0.1 `layouts/console.html`
> **Unblocks** V0.2 exit criterion (approve/reject with audit rows); [B7](B7-provisioning-chain.md) retry button lands here in V0.3
> **Refs** [02-ui.md §4](../02-ui.md) · [01-backend.md §3.4–3.5](../01-backend.md) · [08-testing.md §4](../08-testing.md)

## In plain words

The staff side of the portal: reviewers and admins see a filterable queue of applications, open one to read everything about it (the submitted details, its full history, who has reviewed it so far and what the approval bar requires), and act — record a review, approve, reject, or send back with comments. Every button is just a form that calls the workflow engine; the console itself can't change anything the engine wouldn't allow.

## Background

Reviewers (HTC role) and admins work the application pipeline from the console. In the legacy system this UI ran on client-side role checks and username-string authority; v2's console is server-rendered under a **`ConsoleMixin`** (staff/reviewer gate + nav state in one class — a console screen cannot be added without the gate), and every action goes through `workflow.services.transition()` / `record_review()` — the console has no write path of its own.

v0 scope: the SANDBOX queue and the actions needed for the pilot loop — record review (advisory), approve, reject, send back — plus, once V0.3 lands, provisioning status + manual retry.

## What to build

### Deliverables

| #   | Deliverable                                                                     | Where                                                                               |
| --- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 1   | Console app skeleton: queue + detail views under `ConsoleMixin`                 | `sandbox/console/views.py` + `urls.py`                                              |
| 2   | Queue template: filters (GET), cursor pagination, state counts                  | `sandbox/templates/console/queue.html`                                              |
| 3   | Detail template: payload read-only, timeline, review rows + tally               | `sandbox/templates/console/application_detail.html`                                 |
| 4   | Action forms/views: approve / reject / send back / record review                | thin views → [A5](A5-workflow-state-machine.md)/[A6](A6-reviews-quorum.md) services |
| 5   | V0.3 add-on: provisioning panel + Retry button → [B7](B7-provisioning-chain.md) | detail template partial                                                             |
| 6   | Route-gate rows + guard/permission view tests                                   | `tests/`                                                                            |

### Details

- **Review queue** (`layouts/console.html`):
  - filterable list (state, submitted date; search by reference `SBX-YYYY-NNNNN` / org name) via [A3](A3-applications-model.md)/[A6](A6-reviews-quorum.md) selectors;
  - **cursor pagination** (not offset); filter form is GET (shareable URLs), htmx-upgraded to swap the table only;
  - minimal queue counts by state (v0's "console counts" — a full dashboard is deferred).
- **Application detail**:
  - payload rendered read-only (schema-aware field groups, not raw JSON), org + product summary, transition timeline (from [A5](A5-workflow-state-machine.md) history selectors), review rows for the current round with their comments and a **tally** ("2 approve, 1 send back") beside the approve button — advisory, since approval is the admin's call;
  - **actions as forms**: Approve / Reject / Send back (comment mandatory for reject/send-back), Record review (APPROVE|REJECT|SEND_BACK + comment) — each a plain POST to a thin view calling the Lane A service; guard/permission failures (`DomainError`) render as messages, never 500s; buttons render only when the transition table allows the action _and_ the actor holds the permission (server-side check remains authoritative);
  - **V0.3 add-on**: provisioning panel — ledger rows with per-system state, `PROVISIONING_FAILED` detail, and a **Retry** button posting to [B7](B7-provisioning-chain.md)'s retry service; polling partial shared with [C7](C7-credentials-panel.md).
- Exit-review actions ([A8](A8-exit-workflow.md)) reuse this detail page in V0.4 — keep the action-panel template composable.
- Route-gate rows: every console URL 403/redirects for anonymous, org members and wrong-org members; reviewer vs staff/admin differences asserted (a reviewer can record reviews but cannot approve).

## Acceptance criteria

- [x] Enroll→approve and enroll→reject both drivable entirely from the console, leaving correct transition + review + audit rows. (Driven from [A9](A9-seed-sandbox-demo.md)'s seeded applications; the [C4](C4-enrollment-wizard.md) half of the journey lands with C4.)
- [x] Review tally correct for the current round; admin can approve with zero reviews recorded (advisory, never gating).
- [x] Illegal actions are hidden _and_ rejected server-side if forced (guard tests for an illegal action and for a reviewer forcing approve).
- [x] Queue filters + cursor pagination correct on seeded data; plain-POST pass for every action.
- [x] Matrix rows for all console URLs; djLint/i18n/mypy/ruff clean.

### A decision's comment is recorded as a review

[A5](A5-workflow-state-machine.md) refuses a comment on a review-driven
transition, because the review row is the single home for that text
([03-database.md](../03-database.md)). So `DecideView` records the actor's
comment as their review row first, then transitions without one. Rejecting or
sending back requires a comment; approving does not.

### Reviewers are purely advisory

A reviewer records opinions and moves nothing. `review_application` gates the
review row; every transition needs its own permission, and the seeded reviewer
holds none of them. Asserted both ways — no decision button renders, and a forced
POST is refused by the service.

This reverses what this ticket originally said. It was written when `SEND_BACK`
was gated on `review_application`, so reviewers could ask for changes; [A5](A5-workflow-state-machine.md)
later split `send_back_application` out as its own permission and nothing granted
it to reviewers. The behaviour changed silently — the test was updated to match
the code rather than the intent, which is how a regression becomes a spec.
Whether reviewers *should* be able to send back is [open question 10](../00-master-plan.md#10-open-questions).

### Buttons come from the transition table

`decision_actions` is filtered through `workflow.selectors.available_actions()`,
the same table `transition()` enforces. A screen therefore cannot offer a move
the engine would refuse, and the server-side guard remains authoritative either
way.

### Queue ordering

Cursor pagination keyed on descending `id`, not `created_date`: the seed and any
bulk import create many rows in one transaction, so timestamps tie and are not
stable enough to paginate against.

## Out of scope (deferred)

Full reporting dashboards/exports (P5) · reviewer assignment/routing and its table (P3) · reconciliation alerts (P4) · usage-evidence panel (P4/P5).
