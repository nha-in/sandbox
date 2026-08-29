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

| #   | Deliverable                                                | Where                               |
| --- | ---------------------------------------------------------- | ----------------------------------- |
| 1   | `Application` model + constraints/indexes migration        | `sandbox/applications/models.py`    |
| 2   | Payload schema registry + `SANDBOX` schema-v1 spec         | `sandbox/applications/schemas/`     |
| 3   | `create_draft` / `update_draft` services                   | `sandbox/applications/services.py`  |
| 4   | Org-scoped selectors + console queue queryset              | `sandbox/applications/selectors.py` |
| 5   | Race-safe `SBX-YYYY-NNNNN` reference generator             | services/model layer                |
| 6   | Read-mostly admin · tests for every constraint + validator | `admin.py`, `tests/`                |

### `applications_application`

Extends the shared base model (`external_id`/`created_date`/`modified_date`/`deleted` — [03-database.md §3.1](../03-database.md)):

| Field          | Type                       | Constraints / notes                                                                                     |
| -------------- | -------------------------- | ------------------------------------------------------------------------------------------------------- |
| `reference`    | char(15)                   | `SBX-YYYY-NNNNN`, unique, **display-only** (no URL resolves by it)                                      |
| `kind`         | char + CHECK               | `SANDBOX \| HCX \| UHI \| HIU \| NHCX` — all five in the constraint; only SANDBOX creatable in v0       |
| `product`      | FK → organisations_product | `on_delete=PROTECT`; the organisation is reached through it, so there is one owner of that fact         |
| `applicant`    | FK → user                  | `on_delete=PROTECT`                                                                                     |
| `state`        | char + CHECK               | workflow states; denormalized — written **only** by [A5](A5-workflow-state-machine.md)'s `transition()` |
| `payload`      | JSONB, not null            | versioned envelope (below)                                                                              |
| `submitted_at` | datetime, null             | set on submit                                                                                           |

Constraints & indexes:

- `UNIQUE (product, kind) WHERE state NOT IN ('REJECTED','WITHDRAWN') AND deleted = false` — one live application per product per kind; rejected/withdrawn/deleted never block re-applying, and a second product gets its own application.
- `INDEX (kind, state)` — queue/dashboard queries.
- ~~`GIN (payload jsonb_path_ops)`~~ — **deferred**: specced for ad-hoc admin search, but no admin/search feature reads the payload yet, so it would be pure write-overhead. Add back in the ticket that introduces payload search.
- Org scoping filters `product__organisation` ([A2](A2-users-organisations-org-scoping.md)'s manager).

### Payload envelope + schema registry

```json
{ "schema_version": 1, "data": { "…kind-specific fields…": "…" } }
```

- Registry keyed by `(kind, schema_version)` → validator. v0 registers **`SANDBOX` schema v1**. Field list and choice sets taken from the legacy UI constants (`sandbox-website/src/constants/common-data.js`), not guessed:

  | Payload field          | Legacy source                                                | Rule                                         |
  | ---------------------- | ------------------------------------------------------------ | -------------------------------------------- |
  | `solution_types`       | `sd_login.solution_type` / `solutionTypeOptions` (16 values) | required, `SolutionType` choices             |
  | `solution_type_others` | `solutionTypeOthers`                                         | required **only** when `OTHERS` is selected  |
  | `integration_intents`  | `sd_login.field_detail` / `intentForRequestList` (10 values) | required, `IntegrationIntent` choices        |
  | `payer_categories`     | `payersCategories` (`TPA`, `Insurance company`)              | optional (legacy stored NULL, rendered "NA") |
  | `use_case_narrative`   | `ecosystem` / `intentBehindApplyingForSandbox`               | required, non-blank                          |

  `solution_type` ("what kind of product are you") and `field_detail` ("which ABDM integrations do you intend to build") are **different fields** — an early draft of this ticket conflated them, and validated solution types against catalog milestone keys. They are independent choice sets; neither is a `catalog_milestone` key.

  `integration_level` is **not** in the payload: legacy computes it (`GeneralUtils.setIntegrationLevelInSdLogin(SdExit)`) from exit declarations and only ever renders it as a report column ("Integration Level"/"Integrated Milestones"). It is a workflow output, so it belongs to [A5](A5-workflow-state-machine.md)/[A8](A8-exit-workflow.md), not applicant input.

- **Organisation and product facts do not belong here** — entity type, GST, address, LGD codes, website and product name live on their own tables, so a later edit cannot leave the application showing a stale copy.
- Services validate on **every** write; unknown kind/version → `DomainError`. A corrupted envelope must be unsaveable through services.

Each kind's spec is a Django `Form` in its own module (`schemas/sandbox.py`, later `schemas/hcx.py`), self-registered by a `@register(kind, version)` decorator — the care backend's `resources/<entity>/spec.py` idiom, with Django forms standing in for pydantic specs per [01-backend.md §3.2](../01-backend.md). They live in `schemas/` rather than `forms.py` because the import-linter contract orders `views -> forms -> services`, so `services.py` may not import `forms`; C4's wizard renders the same class the services validate with, via `schemas.payload_form(kind, version)`.

### Services & selectors

```python
# applications/services.py — atomic; payload validated; editable only in DRAFT/SENT_BACK
# ownership is asserted, not assumed: C4 lets the applicant create a new product or
# pick an existing one in the same form, so `product` may be brand new
def create_draft(*, organisation, product, applicant, kind, data) -> Application: ...
def update_draft(*, application, data) -> Application: ...

# applications/selectors.py — reads only
def applications_for_organisation(organisation) -> QuerySet[Application]: ...
def application_detail(organisation, external_id) -> Application: ...   # wrong org ⇒ 404
def console_queue(filters) -> QuerySet[Application]: ...               # C5
```

- Reference generator: `SBX-<year>-<zero-padded sequence>`, race-safe (DB sequence or `select_for_update` counter).
- Admin: read-mostly list (kind/state filters, reference search); payload rendered read-only.

## Acceptance criteria

- [x] Partial-unique constraint tested: duplicate live app rejected; allowed again after REJECTED/WITHDRAWN.
- [x] Payload validation tested valid + invalid + wrong version; corrupted envelope cannot be saved through services.
- [x] References unique and display-only (no URL resolves by reference).
- [ ] Wrong-org detail → 404 (matrix rows added, [C3](C3-route-gate-harness.md)) — selector-level 404 is tested; matrix rows blocked on C3's harness existing, same gap flagged in A2.
- [x] mypy/ruff clean; no ORM writes outside services/model methods.

## Out of scope (deferred)

HCX/UHI/HIU/NHCX schemas + forms (main plan P2) · payload-upgrade data migrations (needed from v2 of a schema) · promotion of payload fields to satellite tables.
