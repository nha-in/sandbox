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

- [ ] Declare-milestone (with a real file) → timeline + document download works; duplicate declaration blocked with a friendly message.
- [ ] Oversize/wrong-type upload rejected with per-file errors, form values preserved.
- [ ] Exit gate: locked until prerequisites; request → console review → approve ⇒ PRODUCTION_APPROVED visible integrator-side; reject → comment shown → re-request works.
- [ ] Every mutation passes with JS disabled; guard violations render as messages, never 500s.
- [ ] Matrix rows added for all URLs; djLint/i18n/mypy/ruff clean.

## Out of scope (deferred)

Conformance runs/evidence gating UI (P5) · WSO2 usage-evidence panel (P4) · milestone tracks beyond the seeded SANDBOX set · public directory of production-approved orgs (P5).
