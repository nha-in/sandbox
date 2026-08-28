# v0 Tickets — Index

One standalone markdown file per v0 work item in [00-master-plan.md §6](../00-master-plan.md). Each ticket is self-explanatory: an engineer should be able to pick one up without reading the whole plan set (links to the reference docs are included for depth).

**Ticket anatomy** — every ticket follows the same shape:

| Section | Audience | Contains |
|---|---|---|
| header block | everyone | lane · phase · depends-on/unblocks · doc refs |
| **In plain words** | everyone | what this is and why it matters, no jargon |
| **Background** | dev | the legacy defect being fixed + design rationale |
| **What to build** | dev | a **Deliverables** table (exact artifact → exact path), then field tables / signatures / behaviour details |
| **Acceptance criteria** | dev + reviewer | testable checkboxes — done means all green |
| **Out of scope** | everyone | deferred items, each naming its v1 phase |

**Baseline assumption: V0.1 Foundation is complete** — it is: the repo is `sandbox-v2/` (Python 3.14, Django 6.0.x, cookiecutter-django layout). When any ticket here is picked up:

- monolith scaffold exists (`config/settings/{base,local,test,production}.py` + `guards.py`), uv + ruff + mypy + djLint + pre-commit (P1)
- `docker compose up` gives Django + Postgres 16 + Redis + Mailpit; non-root Dockerfiles (P2)
- CI enforces ruff / mypy / pytest / djLint / `makemigrations --check` / gitleaks / Trivy (P3)
- staging deploys behind Traefik, Sentry wired (P4); `DEBUG` + non-local DB host hard-fails (P5)
- careui design system ported from `ohcnetwork/experience` (Tailwind v4 standalone via django-tailwind-cli, no node; component classes in `sandbox/static/css/careui.css`; `{% ui_field %}` from `sandbox/theme/templatetags/careui.py`; htmx vendored) + `layouts/{marketing,app,console,error}.html` shells + messages/nav (C1)
- allauth flows work offline: sign-up → email verify → login; staff MFA enforced via `StaffMFARequiredMiddleware` (C2)
- `sandbox/catalog/` app stub exists and hosts the `seed_sandbox_demo` skeleton
- real Keycloak / WSO2 / HIE-CM **sandbox-tier service accounts were requested during V0.1** (longest external lead time — Lane B should confirm access on day one)

**The v0 journey:** register → verify email → apply (SANDBOX kind) → review → provisioned credentials (Keycloak client + WSO2 subscription + HIE-CM bridge) → milestone declarations → exit → production approval.

## Done in V0.1 (no ticket files)

P1 scaffold · P2 compose/Dockerfiles · P3 CI gates · P4 staging+Sentry · P5 local-vs-prod guard · C1 careui port + layouts · C2 allauth templates.

## Lane P — Platform

| Ticket | Phase |
|---|---|
| [P6 — Backup/restore drill + pilot runbook](P6-backup-restore-drill-and-pilot-runbook.md) | V0.4 |

## Lane A — Backend: domain & workflow

| Ticket | Phase |
|---|---|
| [A1 ⚡ — `catalog` app: milestones, seeds, admin](A1-catalog-app.md) | V0.2 |
| [A2 — `users` + `organisations`, membership, org-scoping mixin](A2-users-organisations-org-scoping.md) | V0.2 |
| [A3 — `applications` model: kind + payload envelope + SANDBOX schema](A3-applications-model.md) | V0.2 |
| [A4 — OTP service (Redis token bucket, attempt caps)](A4-otp-service.md) | V0.2 |
| [A5 — Workflow state machine + `transition()` + audit events](A5-workflow-state-machine.md) | V0.2 |
| [A6 — Reviews + quorum guard](A6-reviews-quorum.md) | V0.2 |
| [A7 — Declarations + document uploads](A7-declarations-uploads.md) | V0.4 |
| [A8 — Exit workflow + production approval](A8-exit-workflow.md) | V0.4 |
| [A9 ⚑ — `seed_sandbox_demo`](A9-seed-sandbox-demo.md) | V0.2→V0.4 |

## Lane B — Backend: integrations

| Ticket | Phase |
|---|---|
| [B1 — `integrations` ports + shared HTTP policy](B1-integration-ports-http-policy.md) | V0.3 |
| [B2 ⚑ — Fake adapters for every port](B2-fake-adapters.md) | V0.3 |
| [B3 — Keycloak adapter (`IdpAdmin`)](B3-keycloak-adapter.md) | V0.3 |
| [B4 — WSO2 adapter (`ApiGateway`)](B4-wso2-adapter.md) | V0.3 |
| [B5 — HIE-CM adapter (`BridgeRegistry`)](B5-hiecm-adapter.md) | V0.3 |
| [B6 — Notification adapter + Celery send task + delivery log](B6-notification-adapter.md) | V0.3 |
| [B7 — Provisioning chain + ledger + `PROVISIONING_FAILED` + retry](B7-provisioning-chain.md) | V0.3 |
| [B8 — Deprovisioning chain (rejection path)](B8-deprovisioning-chain.md) | V0.3 |
| [B9 — WireMock contract + fault-injection suite](B9-wiremock-fault-injection-suite.md) | V0.3 |

## Lane C — Full-stack UI

| Ticket | Phase |
|---|---|
| [C3 — Route-gate test harness](C3-route-gate-harness.md) | V0.2 |
| [C4 — Enrollment wizard (SANDBOX) + OTP partial](C4-enrollment-wizard.md) | V0.2 |
| [C5 — Console: review queue + application detail + review actions](C5-console-review-queue.md) | V0.2 |
| [C6 — Integrator dashboard + journey stepper](C6-integrator-dashboard.md) | V0.2 |
| [C7 — Credentials panel: show-once, rotate, polling status](C7-credentials-panel.md) | V0.3 |
| [C8 — Milestone + exit forms with uploads](C8-milestone-exit-forms.md) | V0.4 |
| [C9 — Playwright e2e: full journey + JS-disabled pass](C9-playwright-e2e.md) | V0.4 |

⚑ = junior-suitable starter.

## Dependency sketch

```mermaid
flowchart LR
    subgraph V0.2
        A1 --> A2 --> A3 --> A5 --> A6
        A4
        A3 --> C4
        A4 --> C4
        A5 --> C5
        A6 --> C5
        A5 --> C6
        A2 --> C3
    end
    subgraph V0.3
        B1 --> B2
        B1 --> B3 & B4 & B5 & B6
        B3 & B4 & B5 --> B7 --> B8
        A5 --> B7
        B3 & B4 & B5 & B6 & B7 & B8 --> B9
        B7 --> C7
    end
    subgraph V0.4
        A3 --> A7 --> A8
        A6 --> A8
        A7 & A8 --> C8
        C4 & C5 & C6 & C7 & C8 --> C9
        A9 --> C9
        C9 --> P6
    end
```

`A9` (seed) starts in V0.2 and grows with every model-bearing ticket. B1/B2 can start the moment V0.1 lands, in parallel with Lane A.
