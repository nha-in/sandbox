# C4 — Enrollment wizard (SANDBOX) + OTP partial

> **Lane** C — Full-stack UI · **Phase** V0.2 Apply & review
> **Depends on** [A3](A3-applications-model.md) (draft services + payload schema), [A4](A4-otp-service.md), [A1](A1-catalog-app.md) (address dropdown selectors) · V0.1 careui system + `layouts/app.html`
> **Unblocks** V0.2 exit criterion (enroll→approve / enroll→reject) with [C5](C5-console-review-queue.md)
> **Refs** [02-ui.md §3.2/§4](../02-ui.md) · [01-backend.md §3.3](../01-backend.md) · [00-master-plan.md §6](../00-master-plan.md)

## In plain words

The application form itself: a signed-in integrator walks through a few short steps — organisation details, contact, intended roles and use case — reviews a summary, submits, then types the OTP code sent to their contact address. Progress is saved server-side between steps, so closing the browser loses nothing, and if reviewers send the application back, the same wizard reopens pre-filled with their comments on top. Works fully with JavaScript off.

## Background

The legacy enrollment was four duplicated ~1,000-line React wizard forms. v2 replaces the SPA class entirely: the wizard is server-rendered Django forms rendered with careui's `{% ui_field %}`, with htmx as **progressive enhancement only** — every step is a real POST + redirect that works with JS disabled; `hx-*` upgrades it in place. v0 ships one kind (SANDBOX), but the form-stack structure is what later kinds plug field groups into, so keep the per-kind divergence isolated.

Flow being built: signed-in org member → wizard (product, intended roles, use case) → **verify contact** → submit (`DRAFT → SUBMITTED`).

## What to build

### Deliverables

| #   | Deliverable                                                                   | Where                                       |
| --- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| 1   | Step forms (org → contact → roles/use-case → review-and-submit)               | `sandbox/applications/forms.py`             |
| 2   | Wizard views under `OrganisationMixin` calling A3 services                    | `sandbox/applications/views.py` + `urls.py` |
| 3   | Templates: step pages + `partials/otp_verify.html` + dependent-select partial | `sandbox/templates/applications/`           |
| 4   | Validators replacing the legacy `NoSpecialCharacters`-style rules             | `sandbox/applications/validators.py`        |
| 5   | SENT_BACK re-edit flow + one-live-app redirect                                | views                                       |
| 6   | Route-gate rows + view tests incl. the htmx-headerless full walk              | `tests/`                                    |

### Details

- **Wizard pages** under the `OrganisationMixin`, one Django form per step (render each field with `{% ui_field %}` — don't hand-write `ui-*` into widget attrs), draft persisted server-side between steps via [A3](A3-applications-model.md)'s `create_draft`/`update_draft` (payload → `{"schema_version": 1, "data": …}`); steps derived from the legacy SANDBOX form's field inventory, grouped sensibly (org details → contact → roles/use-case → review-and-submit).
- **Address selects** from catalog selectors; district options depend on state via an htmx dependent-select partial — with a no-JS fallback (full-page re-render preserving entered data).
- **Validation** is server-side only; validators with tests replace the legacy `NoSpecialCharacters`-style rules; errors render inline via `{% ui_field %}` + `components/form_errors.html` and the messages component.
- **Review-and-submit** step renders the assembled payload read-only; submit calls the workflow (`DRAFT → SUBMITTED`) then redirects to the OTP step.
- **OTP partial** (`partials/otp_verify.html`): issue + verify against [A4](A4-otp-service.md); resend with visible cooldown; rate-limit/expiry errors from `DomainError` map to form errors (never a 500). Verification stamps the contact's `*_verified_at`; submit is blocked until both are set. Plain-POST fallback for every action.
- **SENT_BACK editing**: the same wizard reopens pre-filled when the application is sent back; reviewer comments shown at the top; resubmission re-enters the flow.
- One live application per (org, kind): if one exists, the wizard entry redirects to it (constraint violation never bubbles to the user).
- htmx conventions per [02-ui.md §3.2](../02-ui.md): partials in `partials/`, stable swap-target ids, `hx-disabled-elt` + indicator on submits.
- Route-gate rows ([C3](C3-route-gate-harness.md)) for every URL; view tests: each step renders, posts, redirects; the full wizard walk passes with the test client **without htmx headers**.

## Acceptance criteria

- [x] Full enroll → OTP → submitted journey works with JS disabled (test-client walk + manual pass).
- [x] Draft resumable mid-wizard (close browser, return, data intact); SENT_BACK re-edit works.
- [x] Dependent state/district selects work with and without htmx.
- [x] OTP wrong-code caps, expiry and resend cooldown surface as friendly form errors — discharged by [A4](A4-otp-service.md), see below.
- [x] Matrix rows added (anonymous → login; wrong org → 404); djLint clean; i18n-tagged; mypy/ruff clean.

## How it was built

### What the browser pass found that the tests did not

The full journey was walked in a real browser (sign in → 4 steps → submitted),
and it surfaced four defects the test suite was blind to:

1. **The placeholder LGD district codes did not fit the column that stores them**
   — `PENDING-01-01` is 13 characters against `organisation.lgd_district_code`'s
   10, so _no_ enrolment could complete on the checked-in dataset. Nothing had
   ever written an LGD code before, so nothing caught it. The codes are now
   `PEND-01-01`, and `test_every_code_fits_the_column_that_stores_it` asserts the
   property, so a real LGD export that overflows fails a test rather than a form.
2. **Every organisation field was optional**, because the columns are nullable —
   an applicant could submit a profile with no address or entity type. Nullable
   columns are right (an organisation exists before it enrols); the _form_ now
   requires everything except GSTIN (government bodies have none) and address
   line 2.
3. **Auto-generated labels** read "Gst number", "Address line1", "Registered in
   india". Set explicitly.
4. **The review step printed raw Python** — `['EUA']`, `['HIP_M2']` — instead of
   the labels the applicant chose, and titled the application's workflow state
   "State" directly under the address's "State" field.

### There is no OTP step, because A4 already put the gate in front of the wizard

The ticket was written before [A4](A4-otp-service.md) landed with
`VerificationRequiredMiddleware`. That middleware bounces any non-staff user
whose email or phone is unverified to `users:verify_contacts` on _every_
request, so a wizard-local `partials/otp_verify.html` would be unreachable code:
you cannot open step 1 unverified, let alone submit. The AC "submit is blocked
until both are set" is therefore satisfied structurally rather than by a step,
and `test_unverified_contact_cannot_reach_the_wizard` asserts that gate really
covers these URLs instead of assuming it does. Confirmed in the browser too: an
unverified member signing in lands on the verification page and `/applications/new/`
redirects straight back to it.

### The draft is created at the details step, not the product step

[A3](A3-applications-model.md)'s `create_draft` and `update_draft` both call
`validate_payload`, so an `Application` row is always a complete, valid
application — an empty draft cannot be written. The wizard therefore holds the
product choice in the session for one step and creates the row once the payload
form is valid; from that point on the draft is server-side and resumable.

**Open question for A3:** if drafts are meant to hold half-finished work, the
validation belongs on the `SUBMIT` transition rather than on every draft write.
That would let step 3 be resumable mid-form too. Left alone here because it
changes a landed ticket's contract and its tests — tracked as
[open question 5](../00-master-plan.md#10-open-questions).

### Validators say what they mean

Legacy's `REGEX_FOR_NO_SPECIAL_CHARACTERS` was unanchored, so any string
containing one acceptable run passed — `"ok<script>"` included. The replacements
in `validators.py` are anchored. Two rules were deliberately not ported: the
website regex (it rejected ports, paths and query strings, which is a bug, so
Django's `URLValidator` does the job) and character-restricting free prose (it
is why the legacy form rejected ordinary sentences; autoescaping is what makes
output safe, not input filtering).

### One live application per product, not per organisation

The ticket says per (org, kind); A3's constraint is per (product, kind), so a
second product legitimately gets its own application. The rule is enforced by
the choices offered — `products_available_for()` excludes products with a live
application — so the partial-unique constraint can never reach the user as a 500.

### A new access rule in the route-gate matrix

The pre-draft steps carry no object in the URL, so "wrong org → 404" is not the
right assertion: every organisation member is entitled to their own copy of the
screen. `Access.ORG_ENTRY` states that rule — any member gets in, an actor with
no membership (all staff) gets 404, anonymous is sent to login. The steps that
do name an application stay `ORG_SCOPED`.

## Out of scope (deferred)

Other kinds' wizards (P2) · kind-chooser screen (single kind in v0 — route straight to SANDBOX) · file uploads (none in the SANDBOX enrollment; uploads arrive with [A7](A7-declarations-uploads.md)/[C8](C8-milestone-exit-forms.md)).
