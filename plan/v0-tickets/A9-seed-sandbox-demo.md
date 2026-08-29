# A9 ⚑ — `seed_sandbox_demo`: org, users, applications across all states

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 → V0.4 (grows with every model ticket) · **⚑ junior-suitable starter**
> **Depends on** starts after [A2](A2-users-organisations-org-scoping.md)/[A3](A3-applications-model.md); extends with [A5](A5-workflow-state-machine.md)–[A8](A8-exit-workflow.md), [B7](B7-provisioning-chain.md)
> **Unblocks** offline dev for everyone, [C9](C9-playwright-e2e.md) (e2e fixture), staging demo data, [P6](P6-backup-restore-drill-and-pilot-runbook.md)
> **Refs** [03-database.md §4](../03-database.md) · [07-infra-cicd.md §3](../07-infra-cicd.md)

## In plain words

One command — `manage.py seed_sandbox_demo` — fills a fresh database with a believable world: demo companies, users of every role, and applications parked at **every** stage of the journey, including the failure states. Any developer, tester or demo can then click through the whole portal offline in minutes. Run it twice and nothing duplicates; `--fresh` removes exactly what it created and nothing else.

## Background

Legacy development required a VPN and shared environments; local setups were unreproducible. v2 makes offline-first local dev a **first-class deliverable**: `docker compose up` + `manage.py seed_sandbox_demo` + fake adapters ([B2](B2-fake-adapters.md)) must yield a fully navigable portal with data in every interesting state. The same command is the fixture for Playwright e2e, screenshots and staging demos — it is not a nice-to-have.

This ticket stays open across V0.2–V0.4: every model-bearing ticket adds its rows here as part of its own definition of done; the A9 owner keeps the command coherent, idempotent and fast.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Full `seed_sandbox_demo [--fresh] [--password …]` command (grown from the V0.1 skeleton) | `sandbox/catalog/management/commands/seed_sandbox_demo.py` |
| 2 | Seeded universe covering every state (list below), built **via the real services** | same |
| 3 | Scoped `--fresh` (seed-marker keyed) | same |
| 4 | Tests: idempotency, `--fresh` scope, legal seeded history | `sandbox/catalog/tests/` |
| 5 | Offline quick-start section in the repo README | `README.md` |

### Details

- Idempotent (natural keys + `update_or_create`) and transaction-wrapped.
- **Seeded universe** (final V0.4 shape):
  - demo organisation (+ a second org so wrong-org 404s are demonstrable) with OWNER + DEVELOPER members; a reviewer and an admin/staff user (staff MFA-enrollable); known passwords via `--password` (never a hardcoded default in code).
  - SANDBOX applications covering **every state**: DRAFT, SUBMITTED (with partial review tallies), SANDBOX_APPROVED, PROVISIONING, PROVISIONED, PROVISIONING_FAILED (with a failed ledger row for the console retry demo), REJECTED (with deprovisioned ledger rows), SENT_BACK, EXIT_REQUESTED, EXIT_REVIEW, PRODUCTION_APPROVED, EXIT_REJECTED, WITHDRAWN.
  - review rows with mixed decisions across rounds (console tally demonstrable, including a post-send-back round), transition history + audit events consistent with each state (**seed by calling the real services/`transition()`, not raw ORM writes**, so seeded history is legal).
  - declarations + a small uploaded document per relevant app; provisioning-ledger rows in ACTIVE/DISABLED/FAILED; notification log rows.
- `--fresh` deletes **exactly what it seeds** (scoped by a seed marker/known keys), never truncates tables.
- Fast enough to run in CI setup (target: seconds, not minutes).

## Acceptance criteria

- [ ] Running twice ⇒ zero duplicates (test asserts row counts stable).
- [ ] `--fresh` removes only seeded rows (test seeds + creates one manual row + `--fresh` ⇒ manual row survives).
- [ ] Seeded via services: every seeded application has a legal transition history + audit trail.
- [ ] `compose up && seed_sandbox_demo` ⇒ portal navigable offline end-to-end (documented in the repo README).
- [ ] Grows in the same PR as each new model/state (checked in review); CI runs the seed as part of e2e setup.

## Out of scope (deferred)

Legacy data import/cutover tooling (open question #1, before P5) · load-test scale seeding (10k+ apps, P6) · non-SANDBOX kinds.
