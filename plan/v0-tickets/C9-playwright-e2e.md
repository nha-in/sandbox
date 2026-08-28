# C9 — Playwright e2e: full journey, including the JS-disabled pass

> **Lane** C — Full-stack UI · **Phase** V0.4 Milestones, exit & pilot readiness
> **Depends on** everything shipping: [C4](C4-enrollment-wizard.md)–[C8](C8-milestone-exit-forms.md), [A9](A9-seed-sandbox-demo.md) (fixture), [B2](B2-fake-adapters.md) (fakes in CI)
> **Unblocks** V0.4 exit criterion ("complete journey green in e2e"), pilot go/no-go, [P6](P6-backup-restore-drill-and-pilot-runbook.md)
> **Refs** [08-testing.md §3/§5](../08-testing.md) · [07-infra-cicd.md §3](../07-infra-cicd.md) · [02-ui.md §6](../02-ui.md)

## In plain words

A robot browser plays a brand-new integrator: registers, verifies email, fills the wizard, types the OTP; then plays the reviewer and approves; watches credentials appear, reveals and rotates the secret, declares a milestone with a file, requests exit, approves it, and sees "production approved". Then it does the entire thing **again with JavaScript switched off** — proving the portal is real HTML underneath. If this suite is green, the pilot journey works.

## Background

The v0 exit bar is a demonstrated end-to-end journey on the real stack: browser → Django → Celery → (fake) external systems, from registration to production approval. Playwright drives it against the compose stack with fake adapters and seeded data. The **JS-disabled pass is not optional** — it is the enforcement of the architecture's core promise that htmx is progressive enhancement and every mutation is a real form POST.

Two CI tiers (per [07-infra-cicd.md §3](../07-infra-cicd.md)): a smoke subset on every PR; the full suite on main.

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Playwright harness vs compose + seed + fakes, Mailpit API helper | `e2e/` (runner: team choice) |
| 2 | Full-journey scenario (steps below) | `e2e/test_journey*` |
| 3 | Branch scenarios: reject, send-back, provisioning-failure retry, wrong-org 404 | `e2e/` |
| 4 | JS-disabled full pass (`javaScriptEnabled: false`) | same suite, second project/config |
| 5 | PR smoke subset (tagged) + main full-suite CI wiring, failure artifacts | pipeline |
| 6 | "Run locally in one command" doc note | repo README / runbook |

### Details

- **Harness**: a test hook (or fake-adapter knob, [B2](B2-fake-adapters.md)) to trigger provisioning-failure scenarios; stable `data-testid`/semantic selectors.
- **The full v0 journey**, one scenario chain (fresh user, not seeded):
  1. register → verify email (via Mailpit) → login;
  2. enrollment wizard → submit → OTP verify (via Mailpit);
  3. as reviewer/admin: console review → approve (quorum per active policy);
  4. provisioning completes against fakes → integrator dashboard reaches Credentials;
  5. credentials panel: reveal show-once (assert re-render masks it) → rotate → new secret shown once;
  6. milestone declaration with a file upload → timeline shows it;
  7. exit request with documents → console exit approval → PRODUCTION_APPROVED on the dashboard.
- **Branch scenarios** (seeded states where faster):
  - reject path → integrator sees rejection + deprovisioned status (fakes disabled);
  - send-back → re-edit → resubmit;
  - provisioning failure → console `PROVISIONING_FAILED` → retry → PROVISIONED;
  - wrong-org user cannot reach another org's application (404 page).
- **JS-disabled pass**: the full journey re-run with `javaScriptEnabled: false` — every step must complete via plain forms/refresh (polling states verified by manual reload).
- **Smoke subset** for PRs: login, dashboard render, one mutation (per [08-testing.md §5](../08-testing.md)); tag-based selection.
- CI wiring: compose-up + seed + run headless; traces/screenshots on failure uploaded as artifacts; flake policy: no unconditional waits — poll UI state.

## Acceptance criteria

- [ ] Full journey green in CI against compose + fakes; branch scenarios green.
- [ ] **JS-disabled full pass green** — this is a hard gate, not advisory.
- [ ] Show-once semantics asserted in-browser (reveal once, masked after).
- [ ] PR smoke ≤ a few minutes; full suite on main; failure artifacts retained.
- [ ] Runbook note: how to run the suite locally in one command.

## Out of scope (deferred)

Load tests (P6) · axe-core accessibility assertions (main plan P6 — do not block the pilot; add if trivial) · cross-browser matrix (Chromium suffices for v0) · staging-against-real-systems e2e (covered by B7/C7 staging verification).
