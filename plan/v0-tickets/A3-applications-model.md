# A3 — `applications` model: kind + payload envelope + SANDBOX payload schema

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review
> **Depends on** [A2](A2-users-organisations-org-scoping.md)
> **Unblocks** [A5](A5-workflow-state-machine.md), [C4](C4-enrollment-wizard.md), [A9](A9-seed-sandbox-demo.md)
> **Refs** [03-database.md §3](../03-database.md) · [01-backend.md §3](../01-backend.md) · [00-master-plan.md §6](../00-master-plan.md)

## In plain words

The **application** is the central record of the whole portal — one row per enrollment attempt, tracking who applied, what they applied for, and where it is in the pipeline. There are five kinds of enrollment in ABDM; instead of five near-identical tables, we use one table with a `kind` column and a versioned JSON envelope for the fields that differ. v0 turns on only the SANDBOX kind, but the design means adding the other four later is a form + a validation schema — zero database redesign.

## Background

The legacy system implemented five enrollment tracks (SANDBOX, HCX, UHI, HIU, NHCX) as five duplicated services and ~3,300 lines of duplicated wizard forms, even though the tracks share ~60% of fields and 100% of the workflow. v2 collapses them into **one polymorphic `Application` aggregate**: a `kind` column plus a versioned JSONB payload validated per kind.

**v0 ships the polymorphic model but only the SANDBOX kind.** The envelope, validation registry and constraints are the permanent artifacts — HCX/UHI/HIU/NHCX later add a schema + form set, no model change (that is the entire point of shipping the envelope now).

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `Application` model + constraints/indexes migration | `sandbox/applications/models.py` |
| 2 | Payload schema registry + `SANDBOX` schema-v1 validator | `sandbox/applications/schemas.py` |
| 3 | `create_draft` / `update_draft` services | `sandbox/applications/services.py` |
| 4 | Org-scoped selectors + console queue queryset | `sandbox/applications/selectors.py` |
| 5 | Race-safe `SBX-YYYY-NNNNN` reference generator | services/model layer |
| 6 | Read-mostly admin · tests for every constraint + validator | `admin.py`, `tests/` |

### `applications_application`

Extends the shared base model (`external_id`/`created_date`/`modified_date`/`deleted` — [03-database.md §3.1](../03-database.md)):

| Field | Type | Constraints / notes |
|---|---|---|
| `reference` | char(15) | `SBX-YYYY-NNNNN`, unique, **display-only** (no URL resolves by it) |
| `kind` | char + CHECK | `SANDBOX \| HCX \| UHI \| HIU \| NHCX` — all five in the constraint; only SANDBOX creatable in v0 |
| `organisation` | FK → organisation | `on_delete=PROTECT`; org-scoped manager from [A2](A2-users-organisations-org-scoping.md) |
| `applicant` | FK → user | `on_delete=PROTECT` |
| `state` | char + CHECK | workflow states; denormalized — written **only** by [A5](A5-workflow-state-machine.md)'s `transition()` |
| `payload` | JSONB, not null | versioned envelope (below) |
| `submitted_at` | datetime, null | set on submit |

Constraints & indexes:

- `UNIQUE (organisation, kind) WHERE state NOT IN ('REJECTED','WITHDRAWN') AND deleted = false` — one live application per org per kind; rejected/withdrawn/deleted never block re-applying.
- `INDEX (kind, state)` — queue/dashboard queries.
- `GIN (payload jsonb_path_ops)` — ad-hoc admin search only, never app queries.

### Payload envelope + schema registry

```json
{"schema_version": 1, "data": { "…kind-specific fields…": "…" }}
```

- Registry keyed by `(kind, schema_version)` → validator. v0 registers **`SANDBOX` schema v1**: org/contact details, intended HIP/HIU roles, use-case description — final field list from the legacy SANDBOX form.
- Services validate on **every** write; unknown kind/version → `DomainError`. A corrupted envelope must be unsaveable through services.

### Services & selectors

```python
# applications/services.py — atomic; payload validated; editable only in DRAFT/SENT_BACK
def create_draft(*, organisation, applicant, kind, data) -> Application: ...
def update_draft(*, application, data) -> Application: ...

# applications/selectors.py — reads only
def applications_for_organisation(organisation) -> QuerySet[Application]: ...
def application_detail(organisation, external_id) -> Application: ...   # wrong org ⇒ 404
def console_queue(filters) -> QuerySet[Application]: ...               # C5
```

- Reference generator: `SBX-<year>-<zero-padded sequence>`, race-safe (DB sequence or `select_for_update` counter).
- Admin: read-mostly list (kind/state filters, reference search); payload rendered read-only.

## Acceptance criteria

- [ ] Partial-unique constraint tested: duplicate live app rejected; allowed again after REJECTED/WITHDRAWN.
- [ ] Payload validation tested valid + invalid + wrong version; corrupted envelope cannot be saved through services.
- [ ] References unique and display-only (no URL resolves by reference).
- [ ] Wrong-org detail → 404 (matrix rows added, [C3](C3-route-gate-harness.md)).
- [ ] mypy/ruff clean; no ORM writes outside services/model methods.

## Out of scope (deferred)

HCX/UHI/HIU/NHCX schemas + forms (main plan P2) · payload-upgrade data migrations (needed from v2 of a schema) · promotion of payload fields to satellite tables.
