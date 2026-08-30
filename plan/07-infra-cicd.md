# 07 — Infra & CI/CD

**Parent:** [00-master-plan.md](00-master-plan.md) · **Audience:** platform engineers

---

## 1. In plain words

A new engineer should be able to check out the repo, run one command, and have the whole portal working on their laptop — database, emails, fake external systems, demo data — with no VPN and no credentials. Every change goes through an automated pipeline that lints, type-checks, tests, scans for secrets and vulnerabilities, and then deploys to a staging server; nothing reaches production by hand. The containers run as non-root users, secrets come from a secret store at runtime, and a misconfigured laptop physically cannot point at production data.

## 2. Legacy findings

**No CI in either repo**; Java-17 base images running Java-21 bytecode; `chmod -R 777`; root containers; signing keystore COPY'd into images; the `local` profile pointed at production RDS/Redis — the single deadliest misconfiguration, now structurally impossible.

## 3. Design (as built in V0.1)

| Concern | Tool |
|---|---|
| Python/deps | **uv** (lockfile, cache-mounted Docker installs), Python 3.14, Django 6.0 |
| Lint/format | ruff (+ format), djLint for templates, pre-commit |
| Types | mypy (strict on services/selectors/adapters) |
| Tests | pytest + pytest-django + coverage; Playwright for e2e |
| CSS | Tailwind v4 standalone binary via django-tailwind-cli (no node in prod images) |

```
compose/local/django/        # uv multi-stage; start, celery worker/beat, tailwind
compose/production/django/   # non-root `django` user, entrypoint waits for deps
compose/production/traefik/  # TLS, ACME, admin IP allowlist
docker-compose.local.yml     # django, postgres, redis, mailpit, worker+beat
docker-compose.production.yml
```

**Pipeline** — PR: ruff → djLint → mypy → `makemigrations --check` → pytest (+coverage gate) → Tailwind build → gitleaks → Trivy → Playwright smoke. Main: build/push image (SBOM) → deploy staging → e2e → manual gate → production. Rollback = previous image + reversible-migrations policy (additive-first, two-step column drops).

**Environments**

| Env | Auth | Data | External systems |
|---|---|---|---|
| local | allauth, mailpit | `seed_sandbox_demo` | fake adapters (WireMock optional) |
| staging | real | seeded | sandbox-tier Keycloak/WSO2/HIE-CM |
| production | real | live | production integrations |

`config/settings/guards.py` hard-fails on `DEBUG` + non-local DB/Redis.

## 4. v0 (POC)

Most of this doc **is already built** (V0.1). Remaining v0 platform work:

- WireMock profile in compose for the resilience suite ([B9](v0-tickets/B9-adapter-resilience-suite.md)); MinIO (or fake storage) for uploads ([A7](v0-tickets/A7-declarations-uploads.md)).
- e2e stage wiring: compose + seed + Playwright, JS-disabled pass included ([C9](v0-tickets/C9-playwright-e2e.md)).
- Secret-store wiring for the real adapter credentials on staging (service accounts requested at V0.1).
- **Backup/restore drill + pilot runbook** — [P6](v0-tickets/P6-backup-restore-drill-and-pilot-runbook.md).

**Exit criteria:** green-field checkout → `compose up` → seeded, navigable portal in one command; staging deploy + rollback rehearsed; restore drill written up.

## 5. v1 — everything else

| Item | Phase |
|---|---|
| Terraform for platform resources (DB, Redis, buckets, secret store, DNS, ingress) incl. the `/sandbox/v3/v1/*` URL-rewrite rules as code | P4/P6 |
| Keycloak realm/roles/clients-of-record via IaC export — no hand-edited realms | P4 |
| Reference environment: hosted Care instance deployed from IaC, pinned to a Care release + ABDM plug version; published one-command local runner, smoke-tested in CI | P4 |
| Sphinx docs service; production hardening pass; SBOM policy enforcement | P5/P6 |

## 6. Definition of done

**v0**

- [ ] One-command local setup verified from a clean checkout (documented in the repo README).
- [ ] All CI gates enforced (no soft-fail); image runs non-root.
- [ ] Staging deploy + rollback rehearsed; backup/restore drill executed; runbook merged.

**v1**

- [ ] IaC owns platform resources + realm export; reference environment deployed and its local runner published + CI-smoke-tested.
