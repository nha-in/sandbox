# 01 — Backend: Django Apps, Domain Model, Workflow

**Parent:** [00-master-plan.md](00-master-plan.md) · **Audience:** backend engineers · **v0 tickets:** [A1–A9](v0-tickets/README.md), [C3](v0-tickets/C3-route-gate-harness.md)

---

## 1. In plain words

The backend is one Django project. Each business area (users, organisations, applications, workflow, …) is its own Django app with the same internal shape, so any engineer can find their way around any app. The most important idea: **an application moves through a pipeline of states** (draft → submitted → reviewed → approved → provisioned → … → production-approved), and there is exactly **one function in the whole codebase allowed to move it** — `transition()`. Everything else (web pages, admin console, scripts) calls that function, which also writes the history row and the audit trail. Web pages never touch the database directly for writes; they call *services* (write) and *selectors* (read).

## 2. Legacy findings

17 controllers + a 2,252-line constants file with 384 native SQL strings; 5 duplicated enrollment services (~40% duplication); `WorkflowServiceImpl` (849 lines, swallow-all catches) driven by magic status ints; reviewer identity = JWT username string match; the 2-of-4 quorum helpers are dead code; provisioning fires on Super Admin approval alone; approvals/provisioning/logins never audited; a separate unauthenticated `hiu-service` deployable.

## 3. Design

### 3.1 Project layout (as built in `sandbox-v2`)

```
config/
├── settings/{base,local,test,production}.py + guards.py
├── urls.py
└── celery_app.py
sandbox/                     # APPS_DIR
├── users/                   # allauth user, roles, MFA policy          (v0)
├── organisations/           # org, membership, org-scoping mixin      (v0)
├── applications/            # polymorphic Application, wizard, OTP    (v0)
├── workflow/                # state machine, reviews, transitions     (v0)
├── declarations/            # milestone + exit declarations, uploads  (v0)
├── integrations/            # ports + adapters + ledger — see 06      (v0)
├── notifications/           # templated email via gateway, log        (v0)
├── audit/                   # append-only audit events                (v0)
├── catalog/                 # milestones, seeds                        (v0)
├── console/                 # admin/HTC screens, single gate mixin    (v0)
├── reporting/               # selectors over materialized views       (v1)
├── content/                 # docs tree, FAQ, snippets, FTS search    (v1)
├── support/                 # org-scoped tickets                      (v1)
├── skills/                  # Agent Skills registry                   (v1)
├── conformance/             # packs, runs, results                    (v1)
├── assistant/               # flag-gated grounded chat                (v1)
├── templates/               # layouts, components, per-app pages/partials
└── static/
```

### 3.2 Layering (enforced by import-linter + review)

Mirrors the care backend's model/spec/viewset separation, adapted to server-rendered Django:

| File | Owns | care analogue |
|---|---|---|
| `models.py` | schema + domain methods that own state changes | `emr/models/*` |
| `forms.py` | validation + rendering (careui `{% ui_field %}`) | pydantic specs |
| `views.py` | HTTP only — **never writes state** | viewsets (thin) |
| `services.py` | use-cases (writes), `transaction.atomic` | `perform_*`/`handle_*` |
| `selectors.py` | reads | filtersets/queries |

All models extend the shared care-style `BaseModel` ([03-database.md](03-database.md) §3.1): `external_id` UUID lookups, `created_date`/`modified_date`, soft delete. Side-effects (Celery, email) dispatch via `transaction.on_commit`.

### 3.3 HTTP surface

- Server-rendered pages + htmx partials are the primary surface; every mutating endpoint also answers a plain POST with a redirect ([02-ui.md](02-ui.md) §3).
- Django forms rendered via the careui `{% ui_field %}` templatetag; server-side validation is the only validation.
- Uploads: size/MIME/extension validated server-side, django-storages (S3/MinIO), DB keeps metadata + sha256.
- OTP endpoints rate-limited (per-identity + per-IP Redis token bucket).
- Error model: `DomainError(code, message)` raised by services; views translate to form errors/messages — replaces the legacy's 34 exception classes collapsing to HTTP 400.

### 3.4 Workflow engine (the heart)

States, transition table (`TRANSITIONS: dict[tuple[State, Action], Spec]` — the table is data), the single `transition()` entry point, reviews-as-rows, and the admin-permission approve guard are specified field-by-field in tickets [A5](v0-tickets/A5-workflow-state-machine.md) and [A6](v0-tickets/A6-reviews-quorum.md).

### 3.5 Authorization idioms

- `OrganisationMixin`: integrator views resolve the active org from session membership; querysets start from `for_organisation(org)` — wrong-org records **404** (403 confirms existence). Spec: [A2](v0-tickets/A2-users-organisations-org-scoping.md).
- `ConsoleMixin`: staff/reviewer gate + nav state in one class — a console screen cannot be added without the gate.
- Route-gate matrix ([08-testing.md](08-testing.md) §3, ticket [C3](v0-tickets/C3-route-gate-harness.md)): every named URL × every actor asserted in tests; URLconf drift fails CI.

### 3.6 Async work

Celery + beat (Redis broker): provisioning/deprovisioning chains ([06-integrations.md](06-integrations.md)), notification sends with retry + delivery log; v1 adds conformance runs, callback probes, reconciliation sweep, report refreshes.

## 4. v0 (POC)

Everything needed for the SANDBOX-only pilot journey. Dev-level specs live in the tickets:

| Build | Ticket |
|---|---|
| catalog app: milestones, seeds | [A1](v0-tickets/A1-catalog-app.md) |
| users + organisations + membership + org-scoping mixin | [A2](v0-tickets/A2-users-organisations-org-scoping.md) |
| polymorphic application + SANDBOX payload schema | [A3](v0-tickets/A3-applications-model.md) |
| OTP service | [A4](v0-tickets/A4-otp-service.md) |
| state machine + `transition()` + audit | [A5](v0-tickets/A5-workflow-state-machine.md) |
| reviews + admin approve guard | [A6](v0-tickets/A6-reviews-quorum.md) |
| declarations + upload pipeline | [A7](v0-tickets/A7-declarations-uploads.md) |
| exit workflow + production approval | [A8](v0-tickets/A8-exit-workflow.md) |
| `seed_sandbox_demo` | [A9](v0-tickets/A9-seed-sandbox-demo.md) |
| route-gate harness | [C3](v0-tickets/C3-route-gate-harness.md) |

**Exit criteria:** enroll→approve and enroll→reject green with audit rows (V0.2); full journey incl. exit green (V0.4); matrix covers every shipped URL.

## 5. v1 — everything else

| Item | Phase | Builds on (v0 artifact) |
|---|---|---|
| HCX/UHI/HIU/NHCX kinds: payload schemas + form sets | P2 | A3's envelope + registry — no model change |
| Org verification workflow + team invites | P2 | A2's models |
| Evidence-gating guard on milestone evidence (flag-gated) | P3/P5 | A5's pluggable guard point |
| Reviewer assignment/routing | P3 | new `workflow_assignment` table — shape decided with the routing requirements, not before |
| Conformance service (packs/runs/results, Celery runner) | P4/P5 | A7's declarations; reference env as counterparty |
| `next_action(application)` selector + golden-path counter | P5 | A3/A5 selectors |
| Support tickets (lite, SLA timers, attachments) | P5 | A7's upload pipeline |
| Content app + `import_legacy_content` + Postgres FTS | P5 | — (docs stay on the legacy site until then) |
| Agent Skills registry · assistant (flag-gated) · reporting MVs | P5 | catalog seeds, audit trail |

## 6. Definition of done

**v0**

- [ ] Import-linter contracts hold (views→services→selectors layering; integrations only via ports).
- [ ] Every service write atomic; every transition audited.
- [ ] Route-gate matrix covers 100% of named URLs; mypy/ruff clean; no view writes state.

**v1**

- [ ] All five kinds enrollable; evidence gating flag-tested both states.
- [ ] Conformance run end-to-end on seeded data; reporting parity vs legacy snapshot.
