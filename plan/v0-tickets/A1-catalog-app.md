# A1 ⚑ — `catalog` app: milestones, LGD tables, seed fixtures, admin

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review · **⚑ junior-suitable starter**
> **Depends on** V0.1 foundation only (first Lane A ticket)
> **Unblocks** [A2](A2-users-organisations-org-scoping.md) (LGD codes), [A7](A7-declarations-uploads.md) (milestone FK), [C4](C4-enrollment-wizard.md) (address dropdowns)
> **Refs** [03-database.md §3.1/§3.4](../03-database.md) · [06-integrations.md §5](../06-integrations.md) (LGD sync deferred there)

## In plain words

Every form in the portal needs reference data before anything else works: the list of sandbox **milestones** integrators progress through, and India's official **state/district lists** (LGD codes) for address dropdowns. This ticket stores that data in our own database and pre-loads it automatically, so a fresh checkout has working dropdowns with no internet or VPN.

## Background

ABDM Sandbox v2 is a server-rendered Django monolith (htmx + Tailwind, Celery + Redis, Postgres 16) replacing the legacy Spring Boot + React portal. The legacy system kept lookup data in `Mst*` tables of unknown provenance with no migrations tooling. v2 keeps all lookup data in a `catalog` app, seeded by **idempotent** data migrations/fixtures so `migrate` from zero always yields a working system.

In v0 there is **no live LGD sync** (the daily Celery sync is deferred): India state/district lists ship as seeded fixtures so the enrollment wizard's address dropdowns work fully offline.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | `Milestone`, `LgdState`, `LgdDistrict` models + migrations | `sandbox/catalog/models.py` |
| 2 | Idempotent seed data: milestone set + full India LGD states/districts | `db/seeds/` + data migration |
| 3 | Selectors backing the wizard dropdowns | `sandbox/catalog/selectors.py` |
| 4 | Read-mostly admin registration | `sandbox/catalog/admin.py` |
| 5 | Tests: seed idempotency (run twice ⇒ same counts), selectors | `sandbox/catalog/tests/` |

The `sandbox/catalog/` app stub already exists from V0.1 (it hosts the `seed_sandbox_demo` skeleton). Add the models below. Conventions for every table (here and in all later tickets): all models extend the care-style shared base model — `external_id` (UUID, unique, indexed), `created_date`/`modified_date`, soft-delete `deleted` with a filtering default manager ([03-database.md §3.1](../03-database.md)); integer PKs stay internal.

### Models

`catalog_milestone` — referenced later by milestone declarations ([A7](A7-declarations-uploads.md)):

| Field | Type | Constraints / notes |
|---|---|---|
| `key` | slug | unique — stable identifier used by seeds and code |
| `title` | char(200) | display name |
| `track` | char(50) | grouping shown on the milestones page |
| `order` | int | sort within track |
| `is_active` | bool | inactive milestones hidden from integrators |

`catalog_lgd_state`:

| Field | Type | Constraints / notes |
|---|---|---|
| `code` | char(10) | LGD state code, unique |
| `name` | char(100) | |

`catalog_lgd_district`:

| Field | Type | Constraints / notes |
|---|---|---|
| `state` | FK → `catalog_lgd_state` | `on_delete=PROTECT` |
| `code` | char(10) | LGD district code |
| `name` | char(100) | |
| — | | `UNIQUE (state, code)` |

Add role/module lookups **only if** the SANDBOX enrollment form needs them — don't port legacy tables speculatively. Organisations store LGD values **by code, not FK** (a catalog refresh must never break an address) — see [A2](A2-users-organisations-org-scoping.md).

### Seeds, selectors, admin

```python
# catalog/selectors.py
def state_choices() -> list[tuple[str, str]]: ...                       # wizard state dropdown
def districts_for_state(state_code: str) -> QuerySet[LgdDistrict]: ...  # htmx dependent select (C4)
```

- Idempotent seeds: fixtures/data migrations in `db/seeds/` (natural-key `update_or_create`), loaded on `migrate`; safe to re-run.
- Django admin registration, read-mostly (`list_display`, search, ordering).

## Acceptance criteria

- [ ] `migrate` from zero yields populated catalog tables; re-running seeds produces zero duplicates (test asserts counts).
- [ ] Selectors unit-tested; admin usable.
- [ ] No raw SQL; mypy/ruff clean; migrations pass `makemigrations --check` in CI.

## Out of scope (deferred)

Daily LGD Celery sync + `LgdLookup` adapter (main plan P4) · `catalog_agent_skill` (Agent Skills, P5) · role/privilege matrices beyond what the SANDBOX form needs.
