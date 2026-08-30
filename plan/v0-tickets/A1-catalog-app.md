# A1 ⚡ — `catalog` app: milestones, seed fixtures, admin

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review · ⚚ junior-suitable starter
> **Depends on** V0.1 foundation only (first Lane A ticket)
> **Unblocks** [A7](A7-declarations-uploads.md) (milestone FK), [C4](C4-enrollment-wizard.md) (address dropdowns)
> **Refs** [03-database.md §3.1/§3.4](../03-database.md) · [06-integrations.md §5](../06-integrations.md) (LGD lookup deferred there)

## In plain words

The portal needs reference data before anything else works: the list of sandbox **milestones** integrators progress through, and India's state/district lists for address dropdowns. Milestones are ours, so they get a table. State/district data belongs to LGD, not to us — it ships as a **bundled dataset file** the dropdowns read, so a fresh checkout works with no internet or VPN, and we never own a stale copy of somebody else's register.

## Background

ABDM Sandbox v2 is a server-rendered Django monolith (htmx + Tailwind, Celery + Redis, Postgres 16) replacing the legacy Spring Boot + React portal. The legacy system kept lookup data in `Mst*` tables of unknown provenance with no migrations tooling. v2 keeps lookup data it owns in a `catalog` app, seeded by an **idempotent management command** the deploy/setup pipeline runs after `migrate` — separate from schema migrations, since catalog rows are content, not structure.

**LGD state/district are deliberately not modelled.** They are external reference data with an authoritative source; copying them into our schema buys a table, a migration, an admin and a sync job to keep a copy correct. In v0 they are a checked-in dataset file read by the selectors; in P4 the `LgdLookup` adapter ([06-integrations.md](../06-integrations.md)) becomes the source and the selectors swap behind the same signature. Organisations store the chosen values as plain codes ([A2](A2-users-organisations-org-scoping.md)), never an FK, so neither change can break a saved address.

## What to build

### Deliverables

| #   | Deliverable                                                        | Where                                                |
| --- | ------------------------------------------------------------------ | ---------------------------------------------------- |
| 1   | `Milestone` model + migration                                      | `sandbox/catalog/models.py`                          |
| 2   | Idempotent milestone seed data + `seed_catalog` management command | `db/seeds/` + `sandbox/catalog/management/commands/` |
| 3   | LGD dataset file + loader; selectors backing the wizard dropdowns  | `sandbox/catalog/data/`, `selectors.py`              |
| 4   | Read-mostly admin registration                                     | `sandbox/catalog/admin.py`                           |
| 5   | Tests: seed idempotency (run twice ⇒ same counts), selectors       | `sandbox/catalog/tests/`                             |

The `sandbox/catalog/` app stub already exists from V0.1 (it hosts the `seed_sandbox_demo` skeleton). Add the models below. Conventions for every table (here and in all later tickets): all models extend the care-style shared base model — `external_id` (UUID, unique, indexed), `created_date`/`modified_date`, soft-delete `deleted` with a filtering default manager ([03-database.md §3.1](../03-database.md)); integer PKs stay internal.

### Models

`catalog_milestone` — referenced later by milestone declarations ([A7](A7-declarations-uploads.md)):

| Field       | Type      | Constraints / notes                               |
| ----------- | --------- | ------------------------------------------------- |
| `key`       | slug      | unique — stable identifier used by seeds and code |
| `title`     | char(200) | display name                                      |
| `track`     | char(50)  | grouping shown on the milestones page             |
| `order`     | int       | sort within track                                 |
| `is_active` | bool      | inactive milestones hidden from integrators       |

Add role/module lookups **only if** the SANDBOX enrollment form needs them — don't port legacy tables speculatively.

### LGD data (no table)

A checked-in dataset file (states + districts with their LGD codes, provenance and retrieval date recorded in the file header) loaded once at import and cached. No model, no migration, no admin.

### Seeds, selectors, admin

```python
# catalog/selectors.py — signatures stay stable when P4's LgdLookup adapter
# replaces the bundled dataset as the source
def state_choices() -> list[tuple[str, str]]: ...  # wizard state dropdown
def districts_for_state(
    state_code: str,
) -> list[tuple[str, str]]: ...  # htmx dependent select (C4)
```

- Both selectors validate against the dataset, so a hand-posted code that isn't real is rejected server-side.
- Idempotent milestone seeds: `db/seeds/catalog_milestones.json` (natural-key `update_or_create`) loaded by `seed_catalog`, a management command the deploy/setup pipeline invokes after `migrate` (compose `start` scripts locally; never inside a migration) — safe to re-run, and safe to run in production since it only ever adds/updates by key, unlike `seed_sandbox_demo`'s destructive `--fresh`.
- Django admin registration for milestones, read-mostly (`list_display`, search, ordering).

## Acceptance criteria

- [ ] `migrate` from zero + `seed_catalog` yields populated milestones; re-running `seed_catalog` produces zero duplicates (test asserts counts).
- [ ] Selectors unit-tested, including rejection of an unknown state/district code; admin usable.
- [ ] Dropdowns work with no network access (dataset is in the repo).
- [ ] No raw SQL; mypy/ruff clean; migrations pass `makemigrations --check` in CI.

## Out of scope (deferred)

`LgdLookup` adapter replacing the bundled dataset, + its fake and contract tests (main plan P4) · `catalog_agent_skill` (Agent Skills, P5) · role/privilege matrices beyond what the SANDBOX form needs.
