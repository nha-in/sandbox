# C8 — Milestone + exit forms with uploads

> **Lane** C — Full-stack UI · **Phase** V0.4 Milestones, exit & pilot readiness
> **Depends on** [A7](A7-declarations-uploads.md), [A8](A8-exit-workflow.md) (services) · [C6](C6-integrator-dashboard.md) slots · console detail ([C5](C5-console-review-queue.md)) for exit review
> **Unblocks** V0.4 exit criterion (complete journey), [C9](C9-playwright-e2e.md)
> **Refs** [02-ui.md §4](../02-ui.md) · [03-database.md §3.4](../03-database.md) · [00-master-plan.md §6](../00-master-plan.md)

## In plain words

The last two screens of the integrator's journey. **Milestones**: a page listing what they must demonstrate, with a small form per milestone to declare it done and attach evidence files. **Exit**: once the prerequisites are met, a form to request production approval with supporting documents — plus the staff-side panel where an admin approves or rejects that request. Approval turns the dashboard's final step green: production approved.

## Background

After credentials, the integrator's remaining journey is: **declare milestones** (self-declaration in v0 — no conformance service) and **request exit to production** with supporting documents. This ticket ships those screens plus the exit-review surface on the console, closing the loop the pilot is judged on: register → … → PRODUCTION_APPROVED.

All writes go through Lane A services ([A7](A7-declarations-uploads.md)/[A8](A8-exit-workflow.md)); these views collect input and render.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Milestones page: per-milestone status + declaration form + timeline | `sandbox/templates/declarations/milestones.html` + views/forms |
| 2 | Exit page: gate/locked state, declaration + uploads form, status views | `sandbox/templates/declarations/exit.html` + views/forms |
| 3 | Org-scoped presigned-download links wired ([A7](A7-declarations-uploads.md)) | templates |
| 4 | Console exit panel: docs list + approve/reject forms → [A8](A8-exit-workflow.md) | [C5](C5-console-review-queue.md) detail + queue filters |
| 5 | Route-gate rows + upload-abuse/gate view tests | `tests/` |

### Details

**Integrator side** (under `OrganisationMixin`, embedded in the [C6](C6-integrator-dashboard.md) dashboard + dedicated pages):

- **Milestones page**: active milestones from catalog with per-milestone status (not declared / declared + date); **declaration form** per milestone — declaration fields (payload) + optional file uploads (multiple, size/type hints mirrored client-side, enforcement server-side via A7); available only in PROVISIONED state (guard errors → friendly messages); **timeline** of declaration rows with document names → org-scoped presigned downloads.
- **Exit page**: gated on the milestone prerequisite defined in [A8](A8-exit-workflow.md) (locked state shows exactly what's missing); exit declaration form + required document uploads; submission calls `request_exit` → confirmation + status view (EXIT_REQUESTED/EXIT_REVIEW: read-only summary; EXIT_REJECTED: reviewer comment + re-request path per A8; PRODUCTION_APPROVED: prominent success state on page + dashboard stepper).
- Upload UX: plain `multipart/form-data` POST (progressive enhancement first); validation failures re-render preserving field values; per-file server errors listed.

**Console side** (extends [C5](C5-console-review-queue.md) under `ConsoleMixin`):

- Exit queue rows (EXIT_REQUESTED/EXIT_REVIEW) in the review queue filters; application detail gains an **exit panel**: declaration payload read-only, document list (staff presigned downloads), Approve exit / Reject exit (mandatory comment) forms calling [A8](A8-exit-workflow.md) transitions — admin-permission-only.

Route-gate rows for every new URL (milestone pages, uploads, downloads, exit pages, console exit actions): wrong org 404s; downloads never public; exit approval staff/admin-only.

## Acceptance criteria

- [x] Declare-milestone (with a real file) → timeline + document download works; re-declaring supersedes the standing claim rather than duplicating it.
- [x] Oversize/wrong-type upload rejected with per-file errors, form values preserved.
- [x] Exit gate: locked until prerequisites; request → console review → approve ⇒ PRODUCTION_APPROVED visible integrator-side; reject → comment shown → re-request works.
- [x] Every mutation passes with JS disabled; guard violations render as messages, never 500s.
- [x] Matrix rows added for all URLs; djLint/i18n/mypy/ruff clean.

### Built differently from the plan, and why

- **"Duplicate declaration blocked with a friendly message"** became *re-declaring supersedes*. `DeclarationMilestone.superseded_by` exists precisely so a milestone can be re-declared against the same application; blocking it would have left an integrator who attached the wrong file with no way to correct it. Only a **settled** claim is refused, which A7 already does.
- **Two document-download routes, not one.** `declarations:document_download` is scoped by organisation membership, which staff do not have. Rather than teach one view two authorization rules, the console got `console:document_download`, gated by `ConsoleMixin`.
- **`record_review()` was widened to `EXIT_REVIEW`.** The exit decisions are `review_driven`, so `transition()` refuses a comment on them; `record_review()` refused any state but `SUBMITTED`. Between them an exit rejection had nowhere to record a reason. `workflow_review.comment` is already the "single home for the text" in [03-database.md](../03-database.md), so the service was aligned to the schema rather than the schema changed. `current_round()` now counts `SEND_BACK_EXIT` and `REJECT_EXIT` too, or a second exit round would overwrite the first reviewer's row.
- **Milestones and Exit render an empty state for a member with no application**, instead of 404ing. They are permanent sidebar items; a 404 would be the dead link C10's navigation test exists to catch. Writes still require an application.
- **`ui-file` / `ui-file-list` / `ui-file-item` added to `careui-ext.css`.** careui ships no file control, so an upload field fell through to `.ui-input` and rendered as a text box with a browser button loose inside it. The native input is restyled rather than hidden behind a label: a hidden input needs JavaScript to report the chosen filename.
- **No ordering enforcement** (M1 before M2) and **no conformance** anywhere — both deliberately deferred, per the ticket's own out-of-scope list.

### Carried over

- After `APPROVE_EXIT` the application is `PRODUCTION_APPROVED`, which is terminal, so no further milestone can ever be declared. That is **open question 3** (are exits per-milestone-track and repeatable?), already flagged in `machine.py`. Out of scope here.
- The queue's exit filters needed no work: `state_filters` already iterates every `ApplicationState`, and `AWAITING_REVIEW_STATES` already counts `EXIT_REQUESTED`/`EXIT_REVIEW`.

## Out of scope (deferred)

Conformance runs/evidence gating UI (P5) · WSO2 usage-evidence panel (P4) · milestone tracks beyond the seeded SANDBOX set · public directory of production-approved orgs (P5).
