# C6 — Integrator dashboard + journey stepper

> **Lane** C — Full-stack UI · **Phase** V0.2 Apply & review
> **Depends on** [A3](A3-applications-model.md)/[A5](A5-workflow-state-machine.md) selectors · V0.1 `layouts/app.html`
> **Unblocks** the integrator's home for the whole journey; [C7](C7-credentials-panel.md)/[C8](C8-milestone-exit-forms.md) embed into it
> **Refs** [02-ui.md §4](../02-ui.md) · [01-backend.md §3.5](../01-backend.md) · [00-master-plan.md §6](../00-master-plan.md)

## In plain words

The integrator's home page. At a glance: where their application is on the journey (a step tracker: Apply → Verify → Review → Credentials → Milestones → Exit → Production), what state it's in, and a hint about what happens next. While something is in progress — say, credentials being set up — the status refreshes itself every few seconds. Later tickets slot the credentials panel and milestone timeline into this page.

## Background

The dashboard is the signed-in integrator's home: where am I in the sandbox journey, and what happens next? The v0 journey it must narrate: apply → OTP → under review → approved → provisioning → credentials → milestones → exit → production approved. In v0 there is no computed NEXT-ACTION selector and no golden-path day counter (both deferred to P5) — the stepper plus simple state-conditional hints carry that weight.

Server-rendered under `OrganisationMixin`; org-scoped selectors only; no writes from this screen.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Dashboard view under `OrganisationMixin` (read-only) | `sandbox/applications/views.py` (or `dashboard/`) + `urls.py` |
| 2 | Dashboard template: welcome/CTA, stepper, hint card, summary card, slots | `sandbox/templates/dashboard/index.html` |
| 3 | State→step display mapping (covers every state incl. edge states) | template tag / selector |
| 4 | Self-polling `partials/application_status.html` | templates |
| 5 | Route-gate rows + parametrised all-states render test | `tests/` |

### Details

- **Dashboard page** (`layouts/app.html`), resolving the org's live SANDBOX application:
  - **No application yet** → welcome card + "Start your sandbox application" CTA → wizard ([C4](C4-enrollment-wizard.md)).
  - **Application exists** → journey **stepper** (careui `ui-progress-track` / `ui-progress-indicator`): Apply → Verify → Review → Credentials → Milestones → Exit → Production, derived from `Application.state` via a small display mapping (e.g. PROVISIONING/PROVISIONING_FAILED/PROVISIONED all sit at "Credentials" with different badges); terminal/edge states (REJECTED, SENT_BACK, WITHDRAWN, EXIT_REJECTED) render distinct banner + guidance instead of a broken stepper.
  - **State-conditional hint card** (static per state, not computed): e.g. SENT_BACK → "Review comments and edit your application" linking to the wizard; UNDER_REVIEW → expected process copy; PROVISIONED → "Declare your first milestone".
  - **Application summary card**: reference (`SBX-YYYY-NNNNN`), kind, submitted date, state badge (`ui-badge--*`), link to a read-only application view.
  - **Slots** filled by later tickets: credentials panel ([C7](C7-credentials-panel.md), V0.3), milestone timeline + exit status ([C8](C8-milestone-exit-forms.md), V0.4) — leave clearly-marked include points.
- **Status partial** (`partials/application_status.html`): stepper + badge as a fragment; in pending states (SUBMITTED, UNDER_REVIEW, PROVISIONING) it htmx-polls (`hx-trigger="every 4s" hx-swap="outerHTML"`) and stops rendering the trigger at terminal states; plain refresh shows the same truth without JS.
- Rejected/withdrawn orgs can start a fresh application (partial-unique constraint allows it) — CTA reappears.
- Route-gate rows: anonymous → login; wrong-org member sees **their** org's dashboard (never another's data — selector test).

## Acceptance criteria

- [ ] Every workflow state renders a sensible dashboard (parametrised template test over all states — no state falls through to a blank/broken view).
- [ ] Stepper mapping correct for the full state list incl. failure/edge states.
- [ ] Polling partial stops at terminal states and degrades to plain refresh (htmx-off test).
- [ ] Org scoping proven (two-org fixture); matrix rows added.
- [ ] djLint/i18n/mypy/ruff clean; no writes in any dashboard view.

## Out of scope (deferred)

NEXT-ACTION card + `next_action` selector, golden-path day counter (P5) · notification bell/centre, ⌘K (P5) · setup-checklist card (P5) · callback reachability badges (P4).
