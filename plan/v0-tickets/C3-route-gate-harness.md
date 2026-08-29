# C3 — Route-gate test harness (URLconf introspection + actor matrix)

> **Lane** C — Full-stack UI · **Phase** V0.2 Apply & review · built jointly with Lane A
> **Depends on** [A2](A2-users-organisations-org-scoping.md) (org fixtures, mixins) · V0.1 layouts
> **Unblocks** the authz proof for every shipped URL (V0.2 exit criterion); [C4](C4-enrollment-wizard.md)–[C8](C8-milestone-exit-forms.md) all add rows here
> **Refs** [08-testing.md §4](../08-testing.md) · [01-backend.md §3.5](../01-backend.md) · [05-security.md §3.1](../05-security.md)

## In plain words

A living security checklist that cannot go stale. Every web address in the portal is listed in one test table stating who may open it — a stranger, a member of another company, a member, a reviewer, staff — and the suite tries **all of them against every address**. If a developer adds a page and forgets to declare its access rules, the build fails. Forgetting to protect a page becomes structurally impossible.

## Background

The legacy authorization was `permitAll()` on all GETs plus client-side role checks in the React bundle — effectively none. v2's rule: **no view ships without a row in the route-gate test matrix**, and the matrix is mechanically complete because the test suite introspects the URLconf and fails when a URL has no row. This harness is the enforcement mechanism for the whole portal's authz story; it must exist before the feature screens (C4–C8) start landing URLs.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | URLconf-introspecting harness + drift check | `tests/test_route_gates.py` |
| 2 | Declarative matrix: `(url, kwargs_factory, method) × actor → expected` | same |
| 3 | Actor fixtures: two orgs w/ members, reviewer, staff | `tests/conftest.py` (on [A2](A2-users-organisations-org-scoping.md)) |
| 4 | Generic rule assertions (wrong-org 404, console 403, deny-by-default, CSRF) | same |
| 5 | Seeded rows for every URL existing today + "how to add a row" docstring | same |

### Details

- **URLconf introspection**: enumerate every named URL (recursing through includes, excluding third-party internals via an explicit, reviewed allowlist — e.g. allauth URLs get their own rows, django-admin is asserted staff-only+404-for-others as a group).
- **Drift check**: any named URL without a matrix entry ⇒ test failure with a "add a row for `<name>`" message. Removing a URL with a stale row also fails.
- **Matrix format**: one declarative table — `(url_name, url_kwargs_factory, method) × actor → expected` where actors = `anonymous, member_other_org, org_member, reviewer, staff` and expected ∈ {200, 302→login, 403, 404, 405}.
- **Fixture set** (pytest fixtures, built on [A2](A2-users-organisations-org-scoping.md)/[A9](A9-seed-sandbox-demo.md)): two organisations with members, a reviewer, a staff user; object-URL kwargs resolved via factories so wrong-org rows genuinely target another org's object.
- **Baked-in rules** (asserted generically, not per-row):
  - org-scoped object URLs → **404** for `member_other_org` (never 403 — existence must not leak);
  - console URLs → non-staff always 403/redirect, verified **per route** (a forgotten `ConsoleMixin` is caught even though the mixin exists);
  - anonymous on any non-allowlisted URL → redirect to login (deny-by-default with an explicit public allowlist: home, auth, healthz).
  - mutating rows also assert CSRF enforcement (POST without token → 403).
- Seed the matrix with every URL existing at harness-landing time (allauth set + any A2/A3 pages); document "how to add a row" in the test module docstring — every later ticket's DoD references it.

## Acceptance criteria

- [x] Harness enumerates the live URLconf; adding an unlisted URL demonstrably fails CI (proved with a scratch URL: `URLs with no route-gate row: ['scratch_probe']`).
- [x] All five actors exercised per row; wrong-org 404 and console-403 rules hold on every current URL.
- [x] CSRF asserted on mutating rows; public allowlist explicit and reviewed.
- [x] Runs in the normal pytest suite (no special job); 39 route-gate tests in ~1s.
- [x] "Add a row" instructions written; C4–C8 tickets can follow them without touching harness internals.

### Findings

**`users:detail` leaks across users** — recorded as `known_gap` on its row, so the
matrix states the intended rule (`Access.SELF_ONLY`) and the suite carries a
`strict=True` xfail that flips to a failure the moment it is fixed.
`UserDetailView` is a bare `LoginRequiredMixin + DetailView` with no queryset
restriction, addressed by sequential integer pk, and the template renders name
and email — so any signed-in user can enumerate every account. It also breaches
[A2](A2-users-organisations-org-scoping.md)'s criterion that integer PKs never
appear in URLs. Fix belongs in the users app: scope `get_queryset` to
`request.user` and key the URL on `external_id`.

### Access classes

The matrix records a *rule*, not observed behaviour. `Access` values and what
each asserts:

| Access | Anonymous | Others |
|---|---|---|
| `PUBLIC` | must **not** be sent to login | never 403 |
| `AUTHENTICATED` | redirect to login | never 403/404 |
| `SELF_RESOURCE` | redirect to login | holder reaches it; non-holder may 404, never 403 |
| `SELF_ONLY` | redirect to login | owner 200, everyone else **404** |
| `ORG_SCOPED` | redirect to login | other org **404**, never 403 |
| `CONSOLE` | redirect to login | staff reach it, others 403/404 |

`SELF_RESOURCE` was added while building: allauth's MFA device URLs legitimately
404 for a user with no device, and the reviewer/staff fixtures now hold both TOTP
and recovery codes so "gate broken" and "no device" cannot be confused.

## Out of scope

Playwright e2e ([C9](C9-playwright-e2e.md)) · rate-limit tests (OTP covers its own, [A4](A4-otp-service.md)) · pen test (GA prerequisite, not pilot).
