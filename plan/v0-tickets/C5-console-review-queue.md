# C5 — Console: review queue + application detail + review actions

> **Lane** C — Full-stack UI · **Phase** V0.2 Apply & review
> **Depends on** [A5](A5-workflow-state-machine.md), [A6](A6-reviews-quorum.md) (services/selectors) · V0.1 `layouts/console.html`
> **Unblocks** V0.2 exit criterion (approve/reject with audit rows); [B7](B7-provisioning-chain.md) retry button lands here in V0.3
> **Refs** [02-ui.md §4](../02-ui.md) · [01-backend.md §3.4–3.5](../01-backend.md) · [08-testing.md §4](../08-testing.md)

## In plain words

The staff side of the portal: reviewers and admins see a filterable queue of applications, open one to read everything about it (the submitted details, its full history, who has reviewed it so far and what the approval bar requires), and act — record a review, approve, reject, or send back with comments. Every button is just a form that calls the workflow engine; the console itself can't change anything the engine wouldn't allow.

## Background

Reviewers (HTC role) and admins work the application pipeline from the console. In the legacy system this UI ran on client-side role checks and username-string authority; v2's console is server-rendered under a **`ConsoleMixin`** (staff/reviewer gate + nav state in one class — a console screen cannot be added without the gate), and every action goes through `workflow.services.transition()` / `record_review()` — the console has no write path of its own.

v0 scope: the SANDBOX queue and the actions needed for the pilot loop — review, approve (quorum-aware), reject, send back — plus, once V0.3 lands, provisioning status + manual retry.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Console app skeleton: queue + detail views under `ConsoleMixin` | `sandbox/console/views.py` + `urls.py` |
| 2 | Queue template: filters (GET), cursor pagination, state counts | `sandbox/templates/console/queue.html` |
| 3 | Detail template: payload read-only, timeline, review rows + quorum indicator | `sandbox/templates/console/application_detail.html` |
| 4 | Action forms/views: approve / reject / send back / record review | thin views → [A5](A5-workflow-state-machine.md)/[A6](A6-reviews-quorum.md) services |
| 5 | V0.3 add-on: provisioning panel + Retry button → [B7](B7-provisioning-chain.md) | detail template partial |
| 6 | Route-gate rows + guard/permission view tests | `tests/` |

### Details

- **Review queue** (`layouts/console.html`):
  - filterable list (state, submitted date; search by reference `SBX-YYYY-NNNNN` / org name) via [A3](A3-applications-model.md)/[A6](A6-reviews-quorum.md) selectors;
  - **cursor pagination** (not offset); filter form is GET (shareable URLs), htmx-upgraded to swap the table only;
  - minimal queue counts by state (v0's "console counts" — a full dashboard is deferred).
- **Application detail**:
  - payload rendered read-only (schema-aware field groups, not raw JSON), org summary, transition timeline (from [A5](A5-workflow-state-machine.md) history selectors, with actor + comment), review rows + **quorum indicator** ("2 of 3 approvals" / "admin decision pending" per the active `WORKFLOW_QUORUM_POLICY`);
  - **actions as forms**: Approve / Reject / Send back (comment mandatory for reject/send-back), Record review (APPROVE|REJECT|SEND_BACK + comment) — each a plain POST to a thin view calling the Lane A service; guard/permission failures (`DomainError`) render as messages, never 500s; buttons render only when the transition table allows the action *and* the actor holds the permission (server-side check remains authoritative);
  - **V0.3 add-on**: provisioning panel — ledger rows with per-system state, `PROVISIONING_FAILED` detail, and a **Retry** button posting to [B7](B7-provisioning-chain.md)'s retry service; polling partial shared with [C7](C7-credentials-panel.md).
- Exit-review actions ([A8](A8-exit-workflow.md)) reuse this detail page in V0.4 — keep the action-panel template composable.
- Route-gate rows: every console URL 403/redirects for anonymous, org members and wrong-org members; reviewer vs staff/admin differences asserted (reviewer can record reviews but not approve under `ADMIN_UNILATERAL`).

## Acceptance criteria

- [ ] Enroll→approve and enroll→reject both drivable entirely from the console, leaving correct transition + review + audit rows (integration test with [C4](C4-enrollment-wizard.md) output).
- [ ] Quorum indicator correct under both policies (parametrised test).
- [ ] Illegal actions are hidden *and* rejected server-side if forced (guard test).
- [ ] Queue filters + cursor pagination correct on seeded data; plain-POST pass for every action.
- [ ] Matrix rows for all console URLs; djLint/i18n/mypy/ruff clean.

## Out of scope (deferred)

Full reporting dashboards/exports (P5) · reviewer assignment/routing and its table (P3) · reconciliation alerts (P4) · usage-evidence panel (P4/P5).
