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

| #   | Deliverable                                                              | Where                                                         |
| --- | ------------------------------------------------------------------------ | ------------------------------------------------------------- |
| 1   | Dashboard view under `OrganisationMixin` (read-only)                     | `sandbox/applications/views.py` (or `dashboard/`) + `urls.py` |
| 2   | Dashboard template: welcome/CTA, stepper, hint card, summary card, slots | `sandbox/templates/dashboard/index.html`                      |
| 3   | State→step display mapping (covers every state incl. edge states)        | template tag / selector                                       |
| 4   | Self-polling `partials/application_status.html`                          | templates                                                     |
| 5   | Route-gate rows + parametrised all-states render test                    | `tests/`                                                      |

### Details

- **Dashboard page** (`layouts/app.html`), resolving the org's live SANDBOX application:
  - **No application yet** → welcome card + "Start your sandbox application" CTA → wizard ([C4](C4-enrollment-wizard.md)).
  - **Application exists** → journey **stepper** (careui `ui-progress-track` / `ui-progress-indicator`): Apply → Verify → Review → Credentials → Milestones → Exit → Production, derived from `Application.state` via a small display mapping (e.g. PROVISIONING/PROVISIONING_FAILED/PROVISIONED all sit at "Credentials" with different badges); terminal/edge states (REJECTED, SENT_BACK, WITHDRAWN, EXIT_REJECTED) render distinct banner + guidance instead of a broken stepper.
  - **State-conditional hint card** (static per state, not computed): e.g. SENT_BACK → "Review comments and edit your application" linking to the wizard; SUBMITTED → expected process copy; PROVISIONED → "Declare your first milestone".
  - **Application summary card**: reference (`SBX-YYYY-NNNNN`), kind, submitted date, state badge (`ui-badge--*`), link to a read-only application view.
  - **Slots** filled by later tickets: credentials panel ([C7](C7-credentials-panel.md), V0.3), milestone timeline + exit status ([C8](C8-milestone-exit-forms.md), V0.4) — leave clearly-marked include points.
- **Status partial** (`partials/application_status.html`): stepper + badge as a fragment; in pending states (SUBMITTED, PROVISIONING) it htmx-polls (`hx-trigger="every 4s" hx-swap="outerHTML"`) and stops rendering the trigger at terminal states; plain refresh shows the same truth without JS.
- Rejected/withdrawn orgs can start a fresh application (partial-unique constraint allows it) — CTA reappears.
- Route-gate rows: anonymous → login; wrong-org member sees **their** org's dashboard (never another's data — selector test).

## Acceptance criteria

- [x] Every workflow state renders a sensible dashboard (parametrised over all 13 states — each has guidance and either a track or a banner).
- [x] Stepper mapping correct for the full state list incl. failure/edge states.
- [x] Polling partial stops at terminal states and degrades to plain refresh (htmx-off test).
- [x] Org scoping proven (two-org fixture); matrix rows added.
- [x] djLint/i18n/mypy/ruff clean; no writes in any dashboard view.

## How it was built

### Not `ui-progress-track`

This ticket named careui's `ui-progress-track`/`ui-progress-indicator` for the
stepper. They are a _determinate progress bar_: `h-1.5` with `overflow-x-hidden`,
so labelled steps get crushed to six pixels and clipped. The browser showed an
unreadable green smear. The stepper is the badge rail [C4](C4-enrollment-wizard.md)
already uses, which reads correctly and carries `aria-current="step"`.

### The track has seven steps but only six reachable positions

The stepper answers "where am I", and it reads that off `Application.state`.
Six of the seven steps have a state that means "you are here". `milestones` has
none, so it renders only as upcoming or done — never current.

The reason is that **the application stops changing state for the longest part
of the journey**. You reach `PROVISIONED` the moment credentials are issued, and
you stay there while you integrate, while you declare M1, then M2, then M3 — all
the way until you request exit and it becomes `EXIT_REQUESTED`. That work is real
and it is months long, but it is recorded in `declarations`, a different table.
Nothing about it touches `Application.state`.

So `PROVISIONED` covers two quite different situations that a stepper wants to
distinguish:

| What is true                      | What the user is doing       | State         |
| --------------------------------- | ---------------------------- | ------------- |
| Credentials just arrived          | reading them, first API call | `PROVISIONED` |
| Integrating, declaring milestones | the bulk of the sandbox      | `PROVISIONED` |

This ticket assigns `PROVISIONED` to `credentials`, so the highlighted step reads
"Credentials" for that whole period — accurate on day one, stale by week two. The
hint copy compensates ("declare your first milestone"), which is why this is a
wart rather than a defect, but the badge and the copy disagree.

Two ways out, both deliberately not taken here:

- **Map `PROVISIONED` to `milestones` instead.** One line. Trades a wrong
  "Milestones" for the few minutes after provisioning against a right one for the
  months that follow. Contradicts this ticket's wording, though not its intent —
  the ticket's own hint for `PROVISIONED` is a milestones instruction.
- **Read `declarations` as well as `Application.state`** — `credentials` until the
  first milestone declaration exists, `milestones` after. Correct in both
  situations, and natural work for [C8](C8-milestone-exit-forms.md), which builds
  the milestone timeline and already needs those queries.

Worth settling in C8 rather than guessing now.

### The dashboard is the home, so it took the nav slot

`/applications/` is now the integrator's landing page and the first nav entry;
the wizard is reached from its CTA rather than from the header, and the
organisation picker defaults here instead of to the wizard.

## Out of scope (deferred)

NEXT-ACTION card + `next_action` selector, golden-path day counter (P5) · notification bell/centre, ⌘K (P5) · setup-checklist card (P5) · callback reachability badges (P4).
