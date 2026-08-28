# C4 — Enrollment wizard (SANDBOX) + OTP partial

> **Lane** C — Full-stack UI · **Phase** V0.2 Apply & review
> **Depends on** [A3](A3-applications-model.md) (draft services + payload schema), [A4](A4-otp-service.md), [A1](A1-catalog-app.md) (LGD dropdowns) · V0.1 `ui-*` system + `layouts/app.html`
> **Unblocks** V0.2 exit criterion (enroll→approve / enroll→reject) with [C5](C5-console-review-queue.md)
> **Refs** [02-ui.md §3.2/§4](../02-ui.md) · [01-backend.md §3.3](../01-backend.md) · [00-master-plan.md §6](../00-master-plan.md)

## In plain words

The application form itself: a signed-in integrator walks through a few short steps — organisation details, contact, intended roles and use case — reviews a summary, submits, then types the OTP code sent to their contact address. Progress is saved server-side between steps, so closing the browser loses nothing, and if reviewers send the application back, the same wizard reopens pre-filled with their comments on top. Works fully with JavaScript off.

## Background

The legacy enrollment was four duplicated ~1,000-line React wizard forms. v2 replaces the SPA class entirely: the wizard is server-rendered Django forms rendered with careui's `{% ui_field %}`, with htmx as **progressive enhancement only** — every step is a real POST + redirect that works with JS disabled; `hx-*` upgrades it in place. v0 ships one kind (SANDBOX), but the form-stack structure is what later kinds plug field groups into, so keep the per-kind divergence isolated.

Flow being built: signed-in org member → wizard (org/contact details, intended roles, use case) → submit → **OTP verify** → application enters review (`DRAFT → SUBMITTED → OTP_VERIFIED`).

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Step forms (org → contact → roles/use-case → review-and-submit) | `sandbox/applications/forms.py` |
| 2 | Wizard views under `OrganisationMixin` calling A3 services | `sandbox/applications/views.py` + `urls.py` |
| 3 | Templates: step pages + `partials/otp_verify.html` + dependent-select partial | `sandbox/templates/applications/` |
| 4 | Validators replacing the legacy `NoSpecialCharacters`-style rules | `sandbox/applications/validators.py` |
| 5 | SENT_BACK re-edit flow + one-live-app redirect | views |
| 6 | Route-gate rows + view tests incl. the htmx-headerless full walk | `tests/` |

### Details

- **Wizard pages** under the `OrganisationMixin`, one Django form per step (render each field with `{% ui_field %}` — don't hand-write `ui-*` into widget attrs), draft persisted server-side between steps via [A3](A3-applications-model.md)'s `create_draft`/`update_draft` (payload → `{"schema_version": 1, "data": …}`); steps derived from the legacy SANDBOX form's field inventory, grouped sensibly (org details → contact → roles/use-case → review-and-submit).
- **Address selects** from catalog selectors; district options depend on state via an htmx dependent-select partial — with a no-JS fallback (full-page re-render preserving entered data).
- **Validation** is server-side only; validators with tests replace the legacy `NoSpecialCharacters`-style rules; errors render inline via `{% ui_field %}` + `components/form_errors.html` and the messages component.
- **Review-and-submit** step renders the assembled payload read-only; submit calls the workflow (`DRAFT → SUBMITTED`) then redirects to the OTP step.
- **OTP partial** (`partials/otp_verify.html`): issue + verify against [A4](A4-otp-service.md); resend with visible cooldown; rate-limit/expiry errors from `DomainError` map to form errors (never a 500). Success fires `SUBMITTED → OTP_VERIFIED` and redirects to the dashboard ([C6](C6-integrator-dashboard.md)). Plain-POST fallback for every action.
- **SENT_BACK editing**: the same wizard reopens pre-filled when the application is sent back; reviewer comments shown at the top; resubmission re-enters the flow.
- One live application per (org, kind): if one exists, the wizard entry redirects to it (constraint violation never bubbles to the user).
- htmx conventions per [02-ui.md §3.2](../02-ui.md): partials in `partials/`, stable swap-target ids, `hx-disabled-elt` + indicator on submits.
- Route-gate rows ([C3](C3-route-gate-harness.md)) for every URL; view tests: each step renders, posts, redirects; the full wizard walk passes with the test client **without htmx headers**.

## Acceptance criteria

- [ ] Full enroll → OTP → submitted journey works with JS disabled (test-client walk + manual pass).
- [ ] Draft resumable mid-wizard (close browser, return, data intact); SENT_BACK re-edit works.
- [ ] Dependent state/district selects work with and without htmx.
- [ ] OTP wrong-code caps, expiry and resend cooldown surface as friendly form errors.
- [ ] Matrix rows added (anonymous → login; wrong org → 404); djLint clean; i18n-tagged; mypy/ruff clean.

## Out of scope (deferred)

Other kinds' wizards (P2) · kind-chooser screen (single kind in v0 — route straight to SANDBOX) · file uploads (none in the SANDBOX enrollment; uploads arrive with [A7](A7-declarations-uploads.md)/[C8](C8-milestone-exit-forms.md)).
