# C7 — Credentials panel: show-once secret, rotate, polling status partial

> **Lane** C — Full-stack UI · **Phase** V0.3 Credentials
> **Depends on** [B7](B7-provisioning-chain.md) (chain + show-once handoff), [B3](B3-keycloak-adapter.md) (rotate), [C6](C6-integrator-dashboard.md) (dashboard slot)
> **Unblocks** V0.3 exit criterion; the pilot integrator's actual working credentials
> **Refs** [06-integrations.md §3–4](../06-integrations.md) · [02-ui.md §3.2/§4](../02-ui.md) · [05-security.md §3.3](../05-security.md)

## In plain words

The moment of payoff: the integrator watches three progress badges (identity, gateway, bridge) tick to done, presses **Reveal credentials**, and sees their secret **exactly once** — with a copy button and a clear "you won't see this again". Lose it? Press **Rotate** and get a fresh one (shown once, old one dead). We never store the secret; staff can see progress and retry failures but have no way to see anyone's secret, ever.

## Background

This panel is where the integrator receives what the sandbox exists to give them: a Keycloak client id + secret their software uses against WSO2/HIE-CM. The security model is **show-once + self-service rotation**: the secret is displayed exactly once at provisioning (or rotation) and we never persist it — the legacy system stored a plaintext copy in `sd_status.gen_securate` and emailed it; both are banned. All portal access is session-authed and org-scoped; the secret never appears in logs, audit data or notification params.

The panel lives in the [C6](C6-integrator-dashboard.md) dashboard slot and mirrors into the console detail ([C5](C5-console-review-queue.md)) without secret access (staff see status + retry, never secrets).

## What to build

### Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Shared per-system status partial (polling, terminal-stop) | `sandbox/templates/partials/provisioning_status.html` |
| 2 | Credentials panel in the [C6](C6-integrator-dashboard.md) slot: reveal (POST) + masked state | `sandbox/templates/dashboard/credentials_panel.html` + view |
| 3 | `rotate_credentials()` service + confirm-dialog form → [B3](B3-keycloak-adapter.md) | `sandbox/applications/services.py` + view |
| 4 | Console mirror: status + retry, **no reveal path** | [C5](C5-console-review-queue.md) detail partial |
| 5 | Access-rule decision (OWNER-only vs member) recorded + matrix rows | ticket PR + `tests/` |
| 6 | Tests: one-time reveal, rotate, secret-absence greps, JS-off pass | `tests/` |

### Details

- **Status partial** (shared integrator/console): per-system provisioning progress from the [B7](B7-provisioning-chain.md) ledger (Keycloak / WSO2 / HIE-CM with `ui-badge--*` states); while PROVISIONING it htmx-polls every few seconds and stops at terminal states (PROVISIONED / PROVISIONING_FAILED); degrades to plain refresh. Integrator-side PROVISIONING_FAILED copy: "we're on it" + support hint (retry is console-only).
- **Show-once reveal**: on first PROVISIONED render (and after each rotation), the secret comes from B7's one-time-read handoff (short-TTL cache, consumed on read — design shared with B7):
  - rendered once with copy-to-clipboard buttons (tiny inline JS, not an island) + an explicit "you won't see this again" warning;
  - consuming the handoff is a **POST** ("Reveal credentials" button) so a crawler/prefetch GET can never burn the one-time read; after consumption the panel permanently shows client id + `••••` + Rotate.
  - Client id remains always visible (it's not secret); bridge/WSO2 identifiers shown for support reference.
- **Rotate**: POST + confirm dialog (plain-form fallback) → [B3](B3-keycloak-adapter.md) `rotate_client_secret` via a service; new secret enters the same show-once path; action audited; old secret invalid immediately (Keycloak-side truth); double-submit guarded (`hx-disabled-elt` + idempotent service).
- **Access rules**: org members only (decide OWNER-only vs any member for reveal/rotate; record the decision in the ticket PR and matrix rows accordingly); console mirror shows status + retry, no reveal path exists for staff.
- Everything reachable with JS disabled (reveal + rotate as plain POSTs; status via refresh).

## Acceptance criteria

- [ ] Secret visible exactly once: re-render/back/refresh after reveal shows masked state (test: handoff consumed).
- [ ] Rotation: new secret shown once, old invalid (fake-adapter test in CI; real Keycloak on staging), audit row written.
- [ ] Secret absent from DB, logs, audit `data`, notification params (grep/assert tests).
- [ ] Polling stops at terminal states; JS-disabled pass green for reveal + rotate + status.
- [ ] Wrong org 404; staff have no reveal route (matrix rows).
- [ ] Staging: credentials from the panel obtain a Keycloak token and call a sandbox API through WSO2 (V0.3 exit evidence with [B7](B7-provisioning-chain.md)).
- [ ] Staging: **the same call still works after a rotation.** Rotate touches Keycloak only; [B4](B4-wso2-adapter.md)'s `map_keys` left WSO2 holding a copy of the old secret, and WSO2-side rotation is deferred to P4. Expected to be harmless because the gateway validates the JWT rather than the secret — but unverified, and if wrong, rotation bricks a live integrator.

## Out of scope (deferred)

Callback registration + reachability badges (P4) · WSO2-side key rotation (P4) · setup-checklist card (P5).
