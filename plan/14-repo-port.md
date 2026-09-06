# 14 — Rebuilding this repo on `experience`

> **SUPERSEDED (2026-09-06) by `12-abdm-portal-rebuild.md`.** Do not build
> from this document. It is kept only for the record of what changed and
> why; every live decision has moved.

Status: ready to execute (2026-09-05). The mechanical companion to `13`, which
settles *what* the system is; this settles *how this repository becomes it*.

**The move in one line:** delete the machinery, keep the outside edges, copy
`experience` in, rename the package.

The design is already decided — `12` for the shape, `13` for the reconciliation
and the corrections. Nothing here re-opens either. Every count below is read
from the tree, not estimated, and every file that couples to something being
deleted **or replaced** is named.

---

## 1. Removed from this repo

Whole apps. Nothing in them survives; `13` and `12` §11 say why.

| app | src | migrations | replaced by |
| --- | --: | ---------: | ----------- |
| `applications/` | 3,460 | yes | `ApplicationInstance` + the form registry |
| `workflow/` | 1,173 | yes | nothing — `12` chose not to build an engine |
| `console/` | 1,307 | — | `experience`'s `ohc/` |
| `audit/` | 114 | yes | `ApplicationEvent` — §5 |
| `declarations/` | 0 | — | already dead: only `__pycache__`, absent from `LOCAL_APPS` |

**Also removed, from apps that otherwise stay:**

| file | lines | why |
| ---- | ----: | --- |
| `catalog/management/commands/seed_sandbox_demo.py` | 542 | seeds `applications` + `workflow`. `experience` brings `seed_experience_demo` and `seed_hub_demo` |
| `catalog/tests/test_seed_sandbox_demo.py` | 143 | with it |
| `integrations/tests/test_provisioning.py` | 417 | rewritten in step 5, not ported — asserts against `ApplicationState` transitions |
| `integrations/tests/test_deprovisioning.py` | 285 | same |
| `integrations/tests/test_models.py` | 94 | same |
| `notifications/tests/test_hooks.py` | 129 | same |
| `notifications/tests/test_services.py` | 188 | same |
| `programmes/tests/test_abdm.py` | 256 | tests a workflow definition that no longer exists |

**Not quite all 90 templates go.** `templates/notifications/` **stays**: it
holds the six `.txt` bodies the notification adapter renders, and this table
first counted it as empty because the count globbed `*.html`. Deleting it
breaks twenty `test_notification` cases. The rest are replaced by
`experience`'s 156, or deleted with their app:

| deleted with their app | replaced by `experience`'s |
| ---------------------- | -------------------------- |
| `applications/` 9 · `console/` 7 · `journey/` 11 · `declarations/` 0 | `allauth/` 20 · `components/` 12 · `account/` 6 · `organisations/` 5 · `layouts/` 5 · `users/` 3 · `pages/` 3 · `dashboard/` 3 · `partials/` 1 · the four error pages · `base.html` |

Total removed: **~6,054 lines of app source**, **1,512 lines in seven test
modules** (five of which are rewritten in step 5, two deleted outright), the
542-line seed command, and 90 templates.

`notifications/tests/test_tasks.py` (110) has no deleted-app reference and
belongs in §2.1, not here.

### 1.1 The top-level `tests/` directory — 3,483 lines

Outside every app, and easy to miss. It holds the cross-cutting invariants, so
it needs a disposition per file rather than a blanket call.

| file | lines | couples to | disposition |
| ---- | ----: | ---------- | ----------- |
| `test_route_gates.py` | 572 | **32 `applications:` / `console:` URL names** | **rewrite.** The gate matrix is keyed on route names, so the invariant survives and the file does not — re-key onto `experiences:` and `ohc:` |
| `test_enrollment_wizard.py` | 575 | applications, organisations, workflow | **rewrite** against the form registry |
| `test_navigation.py` | 469 | applications, organisations | **rewrite** |
| `test_credentials_panel.py` | 385 | applications, audit, organisations, workflow | **rewrite.** Carries the "the secret appears in no audit row" assertion — that must survive verbatim |
| `test_dashboard.py` | 243 | applications, organisations | **rewrite** — `experience`'s `pages/` has its own dashboard tests; reconcile rather than keep both |
| `integrations/test_chains.py` | 364 | applications, organisations, workflow | **rewrite** with step 5 |
| `integrations/test_faults.py` | 276 | *(none)* | **port** |
| `integrations/wiremock.py` · `conftest.py` | 157 | *(none)* | **port** |
| `test_settings_guards.py` | 43 | *(none)* | **port**, then extend for the new settings |
| `test_stylesheet.py` · `test_template_syntax.py` | 145 | *(none)* | **rewrite** — both assert against this repo's theme, which §4.1 replaces |
| `test_merge_production_dotenvs_in_dotenv.py` | 39 | *(none)* | **replace** with `experience`'s equivalent |
| `conftest.py` | 215 | applications, organisations | **replace with a collection gate** — see below |

**How this directory survives steps 3 and 4.** Its `conftest.py` is the actor
fixture set for `test_route_gates`, built entirely on `applications`, so it
cannot be merged the way `sandbox/conftest.py` can — and while it fails to
import, *nothing in the suite collects*. Replace it with a `collect_ignore`
list naming every module still awaiting its disposition, and delete an entry as
each is rewritten. **The list reaching empty is what finishes §1.1**, and it
keeps the four portable modules (`test_settings_guards`, `test_faults`,
`wiremock`, the integrations `conftest`) running throughout.

Where a single test is blocked on something a later step delivers, prefer a
`skipif` on the thing's *existence* over a hard skip — `catalog`'s LGD
column-width test guards on `Organisation` having `lgd_state_code`, so it
un-skips itself the moment step 6 adds the column.

---

## 2. Kept from this repo

### 2.1 Untouched — no reference to anything deleted

These move zero lines. This is the part of the repo that was worth keeping.

| file | lines |
| ---- | ----: |
| `integrations/ports.py` | 178 |
| `integrations/registry.py` | 59 |
| `integrations/secret_ref.py` | 52 |
| `integrations/naming.py` | 14 |
| `integrations/http.py` | 327 |
| `integrations/fakes.py` | 400 |
| `integrations/admin.py` · `apps.py` | 53 |
| `integrations/keycloak/adapter.py` · `roles.py` | 272 |
| `integrations/wso2/adapter.py` · `apis.py` | 304 |
| `integrations/hiecm/adapter.py` | 197 |
| `integrations/notification/adapter.py` | 179 |
| `notifications/tasks.py` | 97 |
| `notifications/tests/test_tasks.py` | 110 |
| `otp/` — `service.py` · `__init__.py` | 129 |*
| `catalog/models.py` · `selectors.py` · `apps.py` | 68 |†
| `utils/` — `models.py` · `correlation.py` · `errors.py` | 105 |
| **subtotal** | **~2,544** |

† `catalog/selectors.py` has no caller left once the seed command goes (step 1)
and this repo's `organisations/forms.py` and `views.py` are replaced (step 2) —
its only remaining importer is its own test. It is **dead between step 2 and
step 6**, when the LGD fields are re-applied. Do not let that fool anyone into
deleting it.

\* `otp/service.py` calls `notifications.services.send_now`, which §2.2
rewires. `send_now(*, template_key, recipient, context, channel, user)` takes no
application, so it should survive untouched — but `otp/` is untouched only for
as long as that signature is.

Plus the tests that come with them, also untouched: `test_fakes` 322,
`test_http` 366, `test_keycloak` 296, `test_wso2` 301, `test_notification` 290,
`test_hiecm` 221, `test_ports` 91, `test_registry` 82, and the four adapter
stubs (`keycloak_stub` 140, `wso2_stub` 148, `hiecm_stub` 97,
`notification_stub` 43) — **2,397 lines of passing tests that keep working.**

### 2.2 Kept but rewired

Every file here references an app being **deleted or replaced**. The second
half of that matters: §4 replaces `organisations/` wholesale, and two things in
`integrations/` reach into this repo's version of it —
`selectors.is_owner(organisation, user)`, which `experience` does not have (it
has a `Membership.is_owner` *property*, a different shape), and `Product`
(§5.1). Both break at step 2, so both are fixed in step 3, not in the step-5 rewire. §5 has the detail.

Whether a file stops the tree booting depends on whether its import is real or
`TYPE_CHECKING`-guarded. That split is what divides step 3 from step 5 (§6).

| file | lines | reaches | at boot? |
| ---- | ----: | ------- | -------- |
| `integrations/tasks.py` | 492 | `applications` ×2, `workflow.engine` — **runtime** | **fails** — reached via `ready()` → `hooks` → `services` → `tasks` |
| `integrations/selectors.py` | 141 | `applications` *type-only*, plus `CREDENTIAL_STATES` as bare strings (§5.2) | survives — and that is the risk |
| `integrations/credentials.py` | 99 | `audit.services.emit` — **runtime**; `is_owner`; `applications` *type-only* | fails **on import**; its only runtime importer, `applications/views.py`, is deleted in step 1 |
| `integrations/models.py` | 89 | `"applications.Application"` — a **string FK**, which a grep for `sandbox.applications` misses | boots, then **system checks fail** |
| `integrations/services.py` | 83 | `audit.emit`, `workflow.engine.transition`, `workflow.registry.get_workflow` — all **runtime** | **fails** — imported by `hooks.py` |
| `integrations/hooks.py` | 39 | `workflow.engine.register_hook` — **runtime** | **fails** at `AppConfig.ready()` |
| `notifications/services.py` | 154 | `applications` — *type-only* | survives |
| `notifications/models.py` | 149 | `applications` — **runtime**, module scope | **fails** — model registry |
| `notifications/hooks.py` | 111 | `workflow.engine.register_hook` — **runtime** | **fails** at `ready()` |
| `programmes/abdm.py` | 684 | `workflow` — six `"workflow.*"` permission strings | not an installed app; survives |
| **subtotal** | **~2,041** | | |

Both `apps.py` files already defer their `hooks` import into `ready()` with a
comment explaining why — but `ready()` runs at boot, so the deferral buys
nothing here. Fix `hooks.py`; `apps.py` only changes if the register function
goes entirely.

`programmes/abdm.py` is kept only to be mined: read it in step 6 for the M1–M3
role map and the DHIS predicates, then delete it rather than leaving two ABDM
definitions in the tree.

---

## 3. Added from `experience`

`src` excludes tests and migrations. Copied wholesale **except** §3.1, which
must be stripped on arrival.

| app | src | tests | migrations | what it is |
| --- | --: | ----: | ---------: | ---------- |
| `experiences/` | 5,254 | 1,572 | 4 | the engine and the ABDM application |
| `organisations/` | 1,519 | 1,730 | 3 | **replaces** ours (1,039) |
| `support/` | 1,634 | 1,407 | 1 | tickets |
| `ohc/` | 960 | 1,729 | — | the NHA console — **replaces** ours (1,307) |
| `users/` | 840 | 1,245 | 3 | **replaces** ours (670) |
| `events/` | 267 | 772 | 1 | webinars and sessions |
| `pages/` | 254 | 392 | — | dashboard, home, redirects |
| `contrib/` | 10 | — | 4 | the sites shim |
| `theme/` `templates/` `static/` | — | — | — | the CARE theme and 156 templates |
| **total** | **10,738** | **8,847** | | |

**These totals are before §3.1's strip**, which removes ~191 lines of source,
492 of templates and 123+ of tests from `organisations/` and `ohc/` on arrival.

Inside `experiences/`, the pieces `13` refers to constantly:

| file | lines | |
| ---- | ----: | - |
| `views.py` | 1,015 | the applicant workspace and reviewer screens |
| `services.py` | 808 | `perform_application_action` — where `12` E1 lands |
| `abdm/forms.py` | 707 | the nine forms; `13` D1–D11 edit here |
| `definitions.py` | 671 | `ApplicationFormDefinition`, `ActionResult` — E1 |
| `abdm/definition.py` | 611 | the ABDM registry: forms, actions, roles, statuses |
| `models.py` | 367 | the seven engine tables; `is_internal` lands here |
| `permissions.py` · `permission_keys.py` · `registry.py` · `selectors.py` | 157 | |

### 3.1 Removed from `experience` on arrival — the Care plugin

`experience` ships a **second, complete provisioning system**: a Care-plugin
sandbox flow with its own client, Celery chain, console queue and vendor
screens. `12` decision 4 already settled this — the `Sandbox` model is *"kept
and re-pointed, **not deleted with the Care plugin**"* — so the plugin is
decided-deleted and only the model survives. Copying `organisations/` and
`ohc/` in unexamined would import all of it, and step 3's milestone would then
include its tests passing against a client the design has dropped.

| removed on arrival | lines |
| ------------------ | ----: |
| `organisations/care_plugin.py` | 74 |
| `organisations/tasks.py` — `provision_sandbox`, `poll_sandbox`, `send_sandbox_credentials_email` | 117 |
| `organisations/views.py` — `SandboxView`, `SandboxStatusView`, `SandboxRequestView`, and their URLs | — |
| `ohc/views.py` — `SandboxQueueView`, `SandboxProvisionView`, `SandboxRevokeView`, and their URLs | — |
| sandbox templates — `organisations/sandbox.html` 55, `partials/sandbox_status.html` 263, `ohc/sandboxes.html` 92, `sandbox_actions.html` 24, `open_sandbox_button.html` 22, the two credential emails 36 | 492 |
| `organisations/tests/test_sandbox_views.py`, and the sandbox cases in `ohc/tests/test_console.py` and `test_views.py` | 123+ |
| the `CARE_SANDBOX_*` settings block — **seven** entries (base URL, frontend URL, username, password, timeout, poll attempts, poll interval), including `username`/`password` defaulting to `admin`/`admin` | — |
| `organisations/views.py:489` — `sandbox_frontend_context()`, the last reader of `CARE_SANDBOX_FRONTEND_URL` outside the plugin | — |
| **two navigation lines** — see below | 2 |

**Two navigation partials will take the whole site down if they are missed.**
`ohc/partials/console_nav.html:55` reverses `ohc:sandboxes` and
`components/app_nav.html:47` reverses `organisations:sandbox`. Delete the URL
entries without these two lines and every console page and every organisation
page raises `NoReverseMatch` — they render the nav. **Same commit as the
URLs.** Nothing else in the templates reverses a sandbox route or reads a
`.sandbox` attribute; the other files that mention the word are copy text about
the ABDM sandbox.

**Order within this strip:** views before settings, since
`sandbox_frontend_context()` is what still reads `CARE_SANDBOX_FRONTEND_URL`.

**Kept:** `organisations/models.py`'s `Sandbox` model and its migration
`0003_sandbox`. Its `Status` enum is already `requested / provisioning / ready
/ failed`, which is exactly the attempt record `12` §4 wants — see §6 step 5.

`send_sandbox_credentials_email` deserves naming separately: it is the
email-the-credentials practice that `10` says the show-once panel replaces, so
it goes on design grounds and not merely as plugin debris.

---

## 4. Collisions, the theme, and the rename

**Seven paths collide**, not six — `conftest.py` is one of them, and it cannot
be resolved the way the others are.

| path | resolution |
| ---- | ---------- |
| `users/` `organisations/` `static/` `contrib/` | `experience` wins wholesale |
| `templates/` | `experience` wins — 156 against 90 |
| `theme/` | **not a collision, a toolchain swap** — §4.1 |
| `conftest.py` | **merge** — §4.2 |

For the two replaced apps, re-apply in step 6, **using this repo's model as the
source** rather than re-deriving from the plans:

- `users/` — `review_role` (`12` E2). The mobile OTP is **not** state here; it
  stays in `otp/` (`13` R8).
- `users/middleware.py` — **`VerificationRequiredMiddleware`, and this one is a
  live regression until it lands.** It enforced two things `experience` has no
  equivalent for: TOTP for staff (allauth has no "MFA required" setting, and
  the console is where a stolen password does the most damage) and verified
  email *and* phone for everyone else. It cannot be restored before step 6
  because it reads `email_verified_at` / `phone_verified_at` and reverses
  `users:verify_contacts`, none of which exist on `experience`'s `User` — the
  phone half is exactly `13` R8. **Meanwhile `STAFF_MFA_REQUIRED` is a setting
  that guards nothing**, and the console is reachable with a password alone.
- `users/services.py` — 119 lines, dropped with the directory. Read before
  step 6 decides what of it survives.
- `organisations/` — the ABDM identity fields (`12` §6) and the B1–B4 answers
  (`13` R3). Our `Organisation` already carries `category`,
  `nature_of_entity` and the LGD state/district codes that `catalog/` exists to
  serve; those are what to port forward, not to reinvent.

### 4.1 `theme/` is a toolchain swap

Not a directory replacement, and **the copy in §6 step 2 would miss it
entirely**:

| | this repo | `experience` |
| - | --------- | ------------ |
| location | `sandbox/theme/` — a package app inside the project, **deleted in step 2** along with its `tests/test_careui.py`, which imports `applications` and `workflow` | `theme/` at the **repo root**, outside `ohc_experience/` |
| dependency | `django-tailwind-cli>=4.7.0` | `django-tailwind[cookiecutter,honcho,reload]>=4.5.0` |
| build | CLI binary, no Node | npm `static_src/`, `package.json` |
| carries | — | its own `base.html`, the `careui` template tags |

So this touches a dependency, the Tailwind settings block, the justfile build
step, the compose image, and `tests/test_stylesheet.py`. Do it as its own
change, not as part of the bulk copy.

`sandbox/theme` also owns the **styleguide URL** (`path("styleguide/", …)` in
`config/urls.py`) and the `sandbox.theme` entry in both import-linter
contracts. The arriving `theme/` provides neither, so both references go with
it — the URL include is the first thing that stops the tree booting otherwise.

### 4.2 `conftest.py` must merge, not be replaced

Ours (`sandbox/conftest.py`, and `tests/conftest.py` at 215 lines) carries an
**autouse `_reset_integration_fakes`** fixture, plus `mock_s3`, `enable_mfa`
and an MFA-aware `admin_client`. `experience`'s carries `organisation`,
`onboarded_organisation`, `owner_membership` and `sign_in`.

Replacing ours wholesale silently breaks the 2,397 tests §2.1 calls untouched —
the fakes would carry state between tests. Take the union: `experience`'s
fixtures plus our autouse reset and `mock_s3`.

### 4.3 Dependencies, and the lint contract

The merge runs both ways.

| only in `experience` | only here |
| -------------------- | --------- |
| ~~`django-ninja`~~ · ~~`django-cors-headers`~~ (dropped, below) · `django-compressor` · `django-crispy-forms` · `crispy-bootstrap5` · `django-tailwind` | `httpx` · `pybreaker` · `tenacity` · `moto[s3]` · ~~`django-tailwind-cli`~~ (§4.1) |

**Ours are not optional:** `httpx`, `pybreaker` and `tenacity` are what
`integrations/http.py` is built on, and `moto[s3]` is what the `mock_s3`
fixture §4.2 keeps needs. They stay.

**The django-ninja API does not come along — decided 2026-09-05.**
`config/api.py` mounts exactly one router, `/users/`, whose five endpoints all
run through `_get_users_queryset`, which filters to `pk=request.user.pk`. So it
is a self-only read of your own name and email plus a PATCH of your name —
cookiecutter-django's stock scaffold, not something built for this project, and
duplicating the profile view. Drop `config/api.py`, `users/api/`, its URL mount,
and both `django-ninja` and `django-cors-headers`.

**import-linter.** Both contracts in `pyproject.toml` name `sandbox.applications`,
`sandbox.workflow`, `sandbox.audit` and `sandbox.console` in their layers and
source modules. Lint fails at step 1. Rewrite the contracts as part of that
step, and decide whether the arriving apps join the layering.

### 4.4 The rename

`ohc_experience.*` → `sandbox.*` across the copied tree: `LOCAL_APPS`,
`MIGRATION_MODULES`, `ACCOUNT_ADAPTER`, `ACCOUNT_FORMS`,
`SOCIALACCOUNT_ADAPTER`, every `AppConfig.name`, and every intra-tree import.
App *labels* are unchanged (`users`, `organisations`, …), which is what lets
`integrations/models.py` keep a string FK that only needs its target app
renamed, not its label.

**The URL conf merges too, and order matters in one place.** §4.4 covered the
package rename but not `config/urls.py`, which needs the arriving namespaces —
`pages` at `""`, `users`, `organisations`, `ohc/`, `events/`, `support/`, and
`experiences` mounted at `applications/`. One line is order-dependent:

```python
# must precede the allauth include, or an invitation token in the session
# never reaches the form that reads it
path("accounts/signup/", user_signup_view, name="account_signup"),
path("accounts/", include("allauth.urls")),
```

**The settings merge, in full.** `THIRD_PARTY_APPS` gains `tailwind`, `theme`,
`crispy_forms`, `crispy_bootstrap5` and **`compressor`** — the last is easy to
miss because it is a dependency and a template tag but not obviously an app,
and without it every page inheriting `base.html` dies on `{% load compress %}`.
`compressor.finders.CompressorFinder` joins `STATICFILES_FINDERS`. The context
processors change name as well as package: ours were
`organisations.active_organisation` and `.navigation`, the arriving pair are
`users.ohc_team` and `organisations.current_organisation`.

**`TIME_ZONE` conflicts, and ours is right.** This repo sets `Asia/Kolkata`;
`experience` sets `UTC` and three of its event tests assert `"3:00 p.m. UTC"`.
Keep `Asia/Kolkata` and re-assert in IST — the tests' own docstring says they
exist because a bare time "sends an Indian partner to a call five and a half
hours after it ended", which is the case for our zone, not theirs.

**One settings default points at a deleted route.**
`NOTIFICATION_CREDENTIALS_ROUTE` defaults to `applications:step_review`
([base.py:555](../config/settings/base.py)) and is read by
`notifications/hooks.py:58`. Re-point it with the rewire.

### 4.5 Migrations: reset to `0001_initial`

Both trees carry real histories for apps sharing a label, and reconciling them
is not worth writing. Delete every migration in both sets and regenerate once.

**The evidence for this being safe**, since it is the one irreversible step:
`docker-compose.production.yml` and `.github/workflows/release.yml` exist, so a
production path is *configured* — but no environment is running this schema
yet, legacy is a separate system, and the local Docker database is reset and
reseeded rather than migrated. **If any of that has changed, stop here.**

**Append-only weakens, deliberately — decided 2026-09-05.**
`audit/migrations/0002_append_only.py` runs `REVOKE UPDATE, DELETE ON … FROM
CURRENT_USER`; `ApplicationEvent` enforces the same rule in Python, by raising
in `save()`. We go with `ApplicationEvent` as it stands and do **not** port the
revocation. Recorded rather than glossed: the guarantee moves from one the
database enforces against every client to one the ORM enforces against ours, so
a raw `UPDATE` would now succeed. Revisit if anything outside Django is ever
given write access to this database.

---

## 5. The rewiring, file by file

| file | today | becomes |
| ---- | ----- | ------- |
| `integrations/hooks.py` | `register_hook("provisioning_chain", …)` in `AppConfig.ready()` | entries in the approve action's `ActionResult.effects` — `12` E1 |
| | `register_hook("deprovisioning_chain", …)` | the same on reject and withdraw — E4 |
| `integrations/services.py` | `transition(action="RETRY_PROVISIONING")` | step 3: collapses to enqueueing the chain. Step 5: a registry action, permission-checked |
| | `audit.services.emit` | an `ApplicationEvent` write |
| `integrations/tasks.py` | `transition(action="FAIL_PROVISIONING")` | a status write plus an `ApplicationEvent` |
| | `Application` | `ApplicationInstance` |
| | the three `ApplicationState` gates | **`Sandbox.status`** — there are no registry statuses to use, see §6 step 3 |
| `integrations/credentials.py` | `audit.services.emit` (one call, `credentials.rotated`) | an `ApplicationEvent` write |
| `integrations/models.py` | `FK("applications.Application")` | `FK("experiences.ApplicationInstance")` |
| `integrations/selectors.py` | takes `Application` as a parameter — it never queries one | the annotation only |
| | `CREDENTIAL_STATES` — four state **strings**, deliberately not the enum | the equivalent `Sandbox.status` values — §5.2 |
| `notifications/hooks.py` | five workflow hooks | `effects` for four; a direct call from `complete_provisioning` for the fifth — §5.4 |
| `notifications/models.py` `services.py` | `Application` FK and queries | `ApplicationInstance` |
| `programmes/abdm.py` | `"workflow.view_abdm"` ×6 | registry permission keys — then delete the file |

**Nothing behind `ports.py` is touched** — the four adapters, the registry, the
fakes, `secret_ref.py`, `http.py`. `credentials.py` keeps everything it does
with Keycloak (`take_initial_secret`, `rotate_credentials` calling
`get_idp_admin().rotate_client_secret()`, the owner guard, the `secret_ref`
discard, the one-shot return); only its final `emit` changes.

### 5.1 `Product` is abandoned — decided 2026-09-05

`Product` is not deferred, it is removed. One organisation is one product
(`13` §8 Q1), so the tree stops reaching through `application.product` in all
**five** places — four in `integrations/`, one in `notifications/`:

| where | what | becomes |
| ----- | ---- | ------- |
| `credentials.py:77` | `is_owner(application.product.organisation, actor)` | the membership check against `application.organisation` |
| `tasks.py:192` | Keycloak client `display_name=application.product.name` | `application.organisation.display_name` |
| `tasks.py:245` | WSO2 application `name=application.product.name` | the same |
| `tasks.py:279` | HIE-CM bridge `name=application.product.name` | the same |
| `notifications/hooks.py:83` | `"product": application.product.name` in the mail context | the same — dormant until step 5, since step 3 makes the hook body a no-op |

`Organisation.display_name` is the answer for all three names. It is a naming
change visible in Keycloak, WSO2 and HIE-CM, so it lands in step 3 with the
other `organisations` couplings, and existing resources keep the names they
were created with — nothing renames retroactively.

If a vendor ever arrives with two ABDM-integrating products, reintroducing
`Product` is new work, not a restoration.

### 5.2 Provisioning state appears in five places, not three

`tasks.py`'s three gates are the obvious ones (§6 step 3). Two more hide in
`integrations/selectors.py`. The first:

```python
CREDENTIAL_STATES = frozenset(
    {"SANDBOX_APPROVED", "PROVISIONING", "PROVISIONING_FAILED", "PROVISIONED"},
)
```

Written as **strings rather than the enum**, with a comment explaining why —
importing `applications.models` would close a cycle. That is exactly why it
survives step 3's import purge and why a grep for `ApplicationState` misses it.
It decides whether the credentials panel offers a rotate button, so a stale set
means offering rotation for a client that no longer exists — the thing the
comment says it exists to prevent.

The second is `selectors.py:103`:

```python
pending = _("Waiting") if application.state == "PROVISIONING" else _("Not set up")
```

`ApplicationInstance` has `status`, not `state`, so once step 3 retargets the
FK this is an `AttributeError` on first call — not an import error.

Re-anchor both onto `Sandbox.status` in step 5, with the gates.

**Neither can bite before step 5**, which is why they are safe to leave: both
consumers of `CREDENTIAL_STATES` — `applications/views.py:712` and
`console/views.py:265` — are in apps step 1 deletes. Nothing reads it until the
rewritten panel view does. Same dead-window pattern as `catalog/selectors.py`
(§2.1).

### 5.3 The couplings that survive an import purge

§5.1 and §5.2 are two instances of one problem, and it is worth naming as a
class before step 5: **references that are strings or attribute lookups do not
fail at import, so the step-3 unplug will not surface them.** They wait until
the code runs.

The full list, so step 5 has no surprises:

| where | what | why it survives step 3 |
| ----- | ---- | ---------------------- |
| `notifications/hooks.py:59` | `reverse(..., kwargs={"external_id": application.external_id})` | `external_id` is this repo's `BaseModel` UUID. `ApplicationInstance` has no such field, and every `experiences` route keys on `<str:reference>` — so **re-pointing `NOTIFICATION_CREDENTIALS_ROUTE` (§4.4) is not enough; the kwarg changes too** |
| `notifications/hooks.py:99,103` | `application.applicant.email` and `user=application.applicant` | `ApplicationInstance` has `created_by`, not `applicant` |
| `notifications/hooks.py:83` | `application.product.name` | §5.1 |
| `integrations/selectors.py:31` | `CREDENTIAL_STATES` string set | §5.2 |
| `integrations/selectors.py:103` | `application.state == "PROVISIONING"` | §5.2 |

All five live in hook bodies or selector functions that step 3 disconnects, so
they are dormant rather than broken. Step 5 is where they all come due.

### 5.4 `notifications/hooks.py` is five hooks, and one is not an `effects` entry

`HOOK_TEMPLATES` registers five: `notify_rejected`, `notify_provisioned`,
`notify_exit_approved`, `notify_exit_rejected`, `notify_exit_sent_back`.

Four ride human actions and map cleanly onto `ActionResult.effects`.
**`notify_provisioned` does not** — it fires on `COMPLETE_PROVISIONING`, which
the chain itself raises at `tasks.py:324`, with no person acting. It becomes a
direct call from `complete_provisioning`, not an `effects` entry. §5's "the
same `effects`" is right for four of five.

The three exit templates map onto a separate exit process that `13` collapsed
into milestones on one instance, so **which action each exit template now hangs
off is `13`'s to settle**, not this document's.

---

## 6. Order

Two constraints set the shape. **E1 comes before the rewire** — `ActionResult`
today carries `message`, `new_status`, `metadata_updates`, `outcome_updates`
and `query`, no `effects`, so §5 has nothing to attach to until E1 exists. And
**the three `organisations` couplings land in step 3**, because step 2 deletes
what they depend on.

**Step 1 — delete.** §1's five apps, the seven test modules, the seed command,
the 90 templates and their URLs. Rewrite the two import-linter contracts (§4.3)
in the same commit, or lint fails. The tree will not run; expected until step 3.

**Step 2 — copy and rename.** `experience/ohc_experience/*` in, replacing the
colliding paths (§4). Merge `conftest.py` rather than replacing it (§4.2). The
repo-root `theme/` is **not** part of this copy — §4.1, do it separately.
Rename the package (§4.4). Reconcile dependencies (§4.3).

**Step 3 — unplug, then make it boot.** Settle `LOCAL_APPS` and the two
settings trees, and re-point `NOTIFICATION_CREDENTIALS_ROUTE`. **Then unplug,
and only then reset migrations** (§4.5) — `makemigrations` cannot run until
both FKs are retargeted and the dead imports are gone, and the reset is the one
irreversible step, so it goes last rather than first.

The work step 2 made unavoidable. The kept files do not merely stop
functioning — **six of them stop importing, which stops Django starting**, so
this is an *unplug*, not a rewire: strip the dead imports and the hook
registration, leave the behaviour disconnected, and do not attempt to attach
anything to `effects` yet, because `effects` does not exist until step 4.

| file | what step 3 does to it |
| ---- | ---------------------- |
| `notifications/models.py` | retarget the `Application` FK — module-scope import, so the model registry fails without it |
| `integrations/models.py` | retarget the string FK to `experiences.ApplicationInstance` — system checks fail without it |
| `integrations/hooks.py` · `notifications/hooks.py` | drop `workflow.engine.register_hook`; the register functions become no-ops |
| `integrations/services.py` | drop `workflow.engine.transition`, `workflow.registry.get_workflow`; `audit.emit` → `ApplicationEvent`; `retry_provisioning` **and `retry_deprovisioning`** collapse to enqueueing their chains — `retry_provisioning`'s only caller (`console/views.py:393`) dies in step 1 and `retry_deprovisioning`'s only callers are in the deleted `test_deprovisioning.py`, so the `WorkflowTransition` and the `get_workflow(...).permission_for(...)` check both have nowhere to go. Permission checks return as registry actions in step 5 |
| `integrations/tasks.py` | `Application` → `ApplicationInstance`; drop `transition`; **delete the three `ApplicationState` gates** — see below |
| `integrations/credentials.py` | `audit.emit` → `ApplicationEvent`; `is_owner` → the membership check; apply the `Product` decision (§5.1) |

`integrations/selectors.py` and `notifications/services.py` are **not** in this
list: their `applications` imports are `TYPE_CHECKING`-guarded, so they import
fine and can wait for step 5.

**There are no "registry status keys" to swap to, and that is deliberate.**
`tasks.py` gates on `ApplicationState.PROVISIONING` twice and
`SANDBOX_APPROVED` once, and transitions through START, COMPLETE and FAIL. The
ABDM registry has exactly eight statuses — `draft`, `submitted`,
`under_review`, `changes_requested`, `revision_submitted`, `approved`,
`rejected`, `withdrawn` — and none of them is a provisioning state.

**Do not add provisioning statuses to the registry.** It would contradict the
eight that `12` and `13` treat as settled, and it would split application
status from attempt status across two places. Provisioning state belongs on the
`Sandbox` attempt record, whose `Status` enum is already `requested /
provisioning / ready / failed` (`12` §4).

So step 3 simply **deletes the three gates**. That is safe because nothing
calls the chain — the hooks are no-ops by then — and step 5 re-anchors them
onto `Sandbox.status`.

**Milestone:** `experience`'s suite and the 2,397 untouched integration tests
both pass. Provisioning is disconnected — the chains are intact and importable,
but nothing calls them, because the hooks that used to are now no-ops.

> **Executed 2026-09-06** (`1ce4282`): 639 passed, 13 skipped, 1 xfailed, 0
> failures; `check` clean, `makemigrations --check` clean, both contracts kept.
> Of the first 327 failures, 276 were the one missing middleware and 48 the one
> missing `compressor` — nearly all of a bulk port's noise came from three
> settings lines, not from the code. What the plan had wrong is folded into
> §1, §1.1, §4, §4.1 and §4.4 above. Two carried debts leave step 3: staff MFA
> is unenforced until §4's middleware is re-applied, and `programmes/abdm.py`
> still imports the deleted `workflow`, harmless only because nothing imports
> it.

**Step 4 — the engine delta.** `12` E1 and E4, plus `13` §10's access control
in place of `12` E2/E3. E1 (`ActionResult.effects`) is the prerequisite for
everything in step 5; E4 (withdraw) is small and independent. §10 replaces the
`review_role` field with `ReviewRole` and `ReviewRoleAssignment`, and orphans
the platform half of `assignable_roles`, `MANAGE_REVIEW_ACCESS` and the
reviewer side of the access workspace — those go in the same change.

**Step 5 — plug in.** §5, now that `effects` exists: the two no-op register
functions become entries in the approve, reject and withdraw actions' `effects`,
`selectors.py` and `notifications/services.py` get their type-only references
updated, and **every coupling in §5.3 comes due at once** — the panel URL
kwarg, `application.applicant`, `application.product`, and both provisioning-state
sites. None of them failed earlier; step 3 only disconnected them. **Re-point `Sandbox` here, not in step 6** — its
`organisation` OneToOne becomes an `ApplicationInstance` FK, and the gates step
3 deleted come back as checks on `Sandbox.status`. `retry_provisioning` regains
its permission check as a registry action.

Three details the re-point has to settle, since §3.1 kept the model but not the
plugin that shaped it:

- **Drop `facility_name` and `is_facility_empty`.** They describe a Care
  facility, not a provisioning attempt, and nothing outside the deleted plugin
  writes them. `12` §4 already accounts for the rest — *"`status`, `error`,
  `job_id`, `result` already fit"* — so those four stay.
- **`__str__` reads `self.organisation`** and has to follow the FK.
- The migration is a field change on a kept model, so it is its own migration
  here, after the step-3 reset.

Then the tests: rewrite the five deleted modules,
`tests/integrations/test_chains.py` and `test_route_gates.py` against the new
engine; port `test_faults` and `test_settings_guards` (§1.1). **Provisioning
works end to end against the fakes** before any real credential is involved.

**Step 6 — re-apply the design.** `13`'s `MilestoneGrant`, `NotificationLog`
and `is_internal` (`ProvisionedResource` is kept as-is, and `Sandbox` was
re-pointed in step 5); then D1–D11; then re-apply
the `users/` and `organisations/` fields from §4. Mine `programmes/abdm.py` and
delete it. Rewrite the remaining top-level tests (§1.1).

One loose end for the dashboard reconciliation here: `pages/views.py:21`
declares a *"Sign in to your sandbox facility"* tile and line 65 hard-codes
`"sandbox_ready": False`. Nothing breaks when the plugin goes — the tile
already renders as pending — but it then describes a facility that no longer
exists in the design.

Steps 1–3 are mostly mechanical. Steps 4–6 are `13`'s build order.

## 7. Open

**None.** All four closed on 2026-09-05:

| | resolution |
| - | ---------- |
| `Product` | abandoned; `organisation.display_name` names the external resources — §5.1 |
| the django-ninja API | dropped, with `django-ninja` and `django-cors-headers` — §4.3 |
| append-only audit | `ApplicationEvent`'s Python guarantee; the weakening is recorded — §4.5 |
| the M1–M3 role map | supplied by NHA — `13` §2 |

Step 1 can start.
