# 12 — Adapting `experience`: the portal we already have

> **SUPERSEDED (2026-09-06) by `12-abdm-portal-rebuild.md`.** Do not build
> from this document. It is kept only for the record of what changed and
> why; every live decision has moved.

Status: agreed design, ready to build (2026-09-05). Supersedes
`11-workflow-rewrite.md` **as a build plan** — its reasoning largely survives
and is credited below, but the five-verb engine it specifies is not built.
~~The base is now `ohcnetwork/experience`; `sandbox/` contributes domain and
integrations, not machinery.~~

> **Corrected by `13-reconciliation.md` (2026-09-05).** §1 has the port
> backwards: the base is **this repository**. `experience`'s code is copied into
> `sandbox/` and everything unusable here is deleted; what survives is the
> domain and the external integrations. §7 and D6 are also wrong
> about Milestone 4. NHA's documentation site has a Milestone 4 (NHPR) page
> stating that NHPR integration *is* M4 and that it requires M1, M2 and M3 —
> so there are **four** milestones, not three, and a milestone ordering *is*
> stated for M4. §7's "facility registration is not M4" and "there is no
> milestone DAG — anywhere" do not hold. D2 is also narrowed there: NHA runs
> two demos, and only the internal one gates submission. The rest of this
> document stands, including its model in §4.
>
> **E2 and E3 are superseded by `13` §10** (2026-09-06). They put a
> `review_role` field on `User`; NHA roles become data instead — a
> `ReviewRole` / `ReviewRoleAssignment` pair — because administrators manage
> roles at runtime today and a field cannot be granted, audited or scoped. The
> two seams E3 names, `visible_to` and `get_effective_access`, are unchanged.

## 1. Why the base changed

`11-workflow-rewrite.md` existed to make `sandbox/`'s per-workflow state
machine as simple as a declarative form registry. `experience` already **is**
that registry — and it already carries an ABDM application
(`experiences/abdm/`, 1,319 lines: 9 forms, 6 actions, 7 roles, 8 statuses),
a full applicant workspace, an admin console, 159 templates, versioned
attachments, query threads, per-application RBAC, and the same CARE UI theme.

Building the rewrite would mean re-deriving all of that. The two designs
already agree on the substance: no state machine, permissions-only authority,
derived status, immutable append-only rows, history-is-the-rows.

Where they disagreed — `11` §6 put review on each `FormSubmission` — the
disagreement is resolved in `experience`'s favour by decision D1 below, which
is what makes this adaptation cheap.

## 2. The shape

One `ApplicationInstance` per production-access request. Milestones, security
/ WASA, conformance evidence and the exit claim are all **forms on it**; every
filled form is an `ApplicationFormSubmission`; the decision lands in
`ApplicationInstance.outcome`. A second exit six months later is a second
instance of the same type — already legal, there is no unique constraint on
`(organisation, application_type)`.

`MilestoneGrant` is the durable, organisation-level record of what reached
production. A later exit reads it rather than re-deriving from forms, which is
what stops milestone history from being trapped inside one application.

```
PLATFORM      User (+review_role) · Organisation (+ABDM identity fields)
              Membership · Invitation · Ticket · Event

ENGINE        ApplicationInstance · ApplicationFormSubmission
(unchanged)   ApplicationAttachment · ApplicationAccess
              ApplicationQueryThread/Message · ApplicationEvent

NEW           MilestoneGrant · ProvisionedResource · NotificationLog
              Sandbox (re-pointed at ApplicationInstance)
```

### `ApplicationFormDefinition` is code, not a table

The registry's central idea, and the reason the ER diagram has no row for it.
A form definition is a Python class; its only tie to the database is the
string in `ApplicationFormSubmission.form_key`. Same discipline as `sandbox/`'s
`workflow_key` — legal values live in the registry, never in a CHECK.

```
CODE (registry)                                DATABASE
ApplicationDefinition       .key ───────────→  ApplicationInstance.application_type
  ├─ .statuses              .key ───────────→  ApplicationInstance.status
  ├─ .roles                 .key ───────────→  ApplicationAccess.role_key
  ├─ .forms → ApplicationFormDefinition
  │             .key ──────────────────────→  ApplicationFormSubmission.form_key
  └─ .actions → ApplicationAction .key ────→  ApplicationEvent.action_key
```

Renaming a `key` orphans its rows. A registry test pinning known keys is
carried over from `11` §5 unchanged.

## 3. Engine delta — four changes to `experiences/`

Everything else in the engine is untouched.

| # | change | file | why |
| - | ------ | ---- | --- |
| E1 | `ActionResult.effects: tuple = ()`, run `on_commit` in `perform_application_action` | `definitions.py`, `services.py` | the only write-path change. Nothing can currently write `MilestoneGrant` rows or enqueue provisioning on approve — `ActionResult` carries no hook and the service dispatches no signals |
| E2 | `User.review_role` | `users/models.py` | only `is_ohc_team` exists today |
| E3 | branch `ApplicationQuerySet.visible_to` on `review_role` | `experiences/models.py` | today it is `created_by ∪ access_grants`; a standing review team sees nothing until each application is individually granted |
| E4 | `WithdrawApplication` action; `WITHDRAW_APPLICATION` into `COMMON_PERMISSIONS` and the owner role | `definitions.py`, `abdm/definition.py` | live gap: the permission key and the `withdrawn` status both exist, no action reaches either |

E1 is additive — existing definitions declare no `effects` and behave exactly
as today.

## 4. New models

| model | shape | notes |
| ----- | ----- | ----- |
| `MilestoneGrant` | `organisation` · `milestone` · `granted_by → ApplicationInstance` · `granted_at` · `roles_attached` · `roles_attached_at` | written by the approve action's `effects` (E1). Organisation-scoped — see Q1 |
| `ProvisionedResource` | `application` · `system` (keycloak/wso2/hiecm) · `external_ref` · `public_ref` · `secret_ref` · `state` | ported from `sandbox/integrations/models.py`. **The credentials are the fact** (`11` §7) |
| `NotificationLog` | `event → ApplicationEvent` · `recipient` · `channel` · `template_key` · `status` · `sent_at` | |
| `Sandbox` | re-point `organisation` (OneToOne) → `application` (FK) | kept, not deleted. Becomes the per-application provisioning **attempt** record — `status`, `error`, `job_id`, `result` already fit. Without it, "the run failed before creating any resource" has no row to live on |

The attempt/resource split is `11` §7's, and it is the reason `Sandbox` earns
its place rather than being folded into `ProvisionedResource`.

## 5. ABDM domain fixes

Each of these is settled by a source in §7 — none is a judgment call.

| # | change | where |
| - | ------ | ----- |
| D1 | health information types 6 → 8: add `HealthDocumentRecord`, `Invoice` | `abdm/forms.py` `IntegrationScopeForm` |
| D2 | exit gate — functional-test evidence present · a `wasa`-typed `security_certification`, unexpired · NHA demo recorded | `SubmitApplication.extra_availability` |
| D3 | drop `wasa_certificate_number` from `SecurityComplianceForm` | it duplicates `SecurityCertificationForm.certificate_number`, which is the copy with `expires_on` and renewal. One home for one fact |
| D4 | decision-time ceiling on `ApprovalForm.approved_milestones` — narrow via `__init__` to what was declared | today it offers the full list, so a reviewer can approve a milestone nobody claimed (`11` §10's ceiling, kept) |
| D5 | `ABDM_ROLES` gains `hrp` (Health Repository Provider) | present in legacy's role map, absent from experience's three |
| D6 | `MILESTONES` stays `[m1, m2, m3]` | matches NHA's taxonomy. See §7 and Q2 |

The fields D2 needs all already exist: `ConformanceEvidence` carries
`functional_testing_agency`, `functional_certificate_number`,
`demonstration_date`, `demo_recording_url`; WASA is a `security_certification`
submission; `TechnicalReadiness.production_callback_url` is the callback the
exit form must carry.

## 6. Ported from `sandbox/`

| what | size | notes |
| ---- | ---- | ----- |
| `integrations/` — Keycloak · WSO2 · HIECM · notification adapters, ports, registry, `secret_ref`, tasks | ~2,500 non-test lines | **the largest item.** Re-anchor the trigger from an engine transition onto E1's `effects`. `11` §7 already states it has zero contact with `workflow/`, which is what makes it portable |
| predicates — `covered` / `approved_types` / `dhis_enabled` / `is_compliant` | ~100 lines | rewritten to read `MilestoneGrant` rows rather than the `ExitGrant` dataclass |
| `catalog/` (LGD states & districts) | small | if the address forms need it |
| `otp/` | small | if phone verification stays |

Organisation gains the ABDM identity fields: `sandbox_client_id`,
`production_client_id`, `legacy_sd_id`, `category`, `nature_of_entity`,
`is_individual`, `email_verified_at`, `mobile_verified_at`, `listing_hidden`.

## 7. Sourced facts

Recorded because three of them overturn assumptions inherited from legacy or
from `09-redesign.md`. Sources: the NHA sandbox FAQ
(`sandbox.abdm.gov.in/sandbox/v3/faq`, five tabs) and the linked *Commonly
Asked Questions — Integrator Guide, ABDM ABHA V3 APIs*, v1.4, 20 Nov 2025
(`sandboxcms.abdm.gov.in/uploads/FAQ_20_11_2025_808a25df64.pdf`).

**There are three milestones.** *"There are mainly three different
Milestones"* — M1, M2, M3. All 51 questions in the integrator guide are tagged
`(Milestone 1|2|3)`; nothing is tagged M4, PHR, Health Locker or NHCX.
Legacy's seven date pairs conflate three different kinds of thing:

| legacy column | what it actually is |
| ------------- | ------------------- |
| `m1` `m2` `m3` | milestones |
| `m4` | in `INTEGRATION_FOR_SANDBOX_MILESTONES`, absent from NHA's current taxonomy |
| `phr` | an API surface (own base-URL row) and a participant category |
| `healthLocker` | a participant category — already `ABDM_ROLES` |
| `nhcx` | a separate enrollment track (`03-database.md` §`kind`, `overview.md` §20) |

So `experience`'s existing three-item list was right and legacy's seven was
the anomaly. PHR and Health Locker are already correctly modelled as roles.

**The exit gate, verbatim** (integrator guide p.3): *"The Exit Form should be
filled only after successful completion of FT and WASA certification, along
with the internal demo by NHA. The Callback URL must be specified when
submitting the Exit Form."* This is D2, sourced rather than inferred.

**There is no milestone DAG — anywhere.** The FAQ's *"What are the
prerequisites for integration?"* answers with technical setup only: create
client ID and secret → generate an authorization token → register the
endpoint URL on `dev.abdm.gov.in/devservice/v1/bridges` — verbatim what
`10-production-truth.md` §96 already records. The milestone descriptions imply
ordering (M2 links records to ABHA) but it is never stated as a gate.
`MILESTONE_PREREQS` in `programmes/abdm.py` is therefore a **design judgment
of `09-redesign.md`, not an inherited rule** — see Q3.

**Facility registration is not M4.** Registering at `hspsbx.abdm.gov.in`
yields the HIP-ID / HIU-ID, and *"the same facility ID"* serves both roles —
HIP for M2, HIU for M3. A setup step, not a milestone, and not a dependency
of M2 on M4.

**Mandatory HI types per participant category** (integrator guide p.2) — a
better-sourced cousin of the DHIS matrix, worth reconciling against
`SOLUTION_TYPE_MILESTONES` when that predicate is ported: HMIS → all 8 · LMIS
→ per business case for M2 · Pharmacy → Invoice mandatory · PHR App / Health
Locker / Health Worker → all 8 · Insurance / TPA / Claim Exchange → all 8 if
implementing M3 · Technology Solutions Provider (DSC) → per business case.
Note the categories are close to but not identical with `SolutionType`: no
Telemedicine, and Insurance/TPA/Claim Exchange is NHCX territory.

## 8. Decisions log

1. **Review is application-level** (2026-09-05). The decision lands in
   `ApplicationInstance.outcome`; `MilestoneGrant` rows are written from the
   exit approval. Consciously departs from `11` §6 (per-`FormSubmission`
   review): milestones become self-declarations and the exit review is the
   single gate. This is what keeps `ApplicationFormSubmission` untouched and
   is the largest single saving in the plan.
2. **Milestones stay a field, not a form each.** `IntegrationScopeForm`'s
   `milestones` remains the only home. Per-milestone form definitions were
   only ever justified by per-form review, which D1 removes. Prerequisites, if
   enforced at all, belong in `clean()` beside the existing `hip→m2` /
   `hiu→m3` rules — a validation, not a visibility question.
3. **No root container.** A parent above `ApplicationInstance` would need its
   own status, permissions, access and audit — and `ApplicationAccess`,
   `ApplicationQueryThread` and `ApplicationEvent` all FK to
   `ApplicationInstance`, so queries and audit would either fragment across
   children or move up with it. That is the engine rebuilt one level higher.
   One instance instead; `MilestoneGrant` carries the cross-exit fact.
4. **`Sandbox` is kept and re-pointed**, not deleted with the Care plugin. It
   is the attempt record that `ProvisionedResource` cannot be.
5. **Withdrawal is reachable** (E4). Legacy parity, and `11` §3 preserved it
   everywhere including post-approval.

## 9. Open questions

1. **Product.** `experience` has no Product concept; `sandbox_client_id` and
   `production_client_id` sit directly on `Organisation`, so one organisation
   is one product, and `MilestoneGrant` is organisation-scoped. `sandbox/`
   anchored grants to `Product`. *Held by decision — blocks nothing until a
   vendor arrives with two ABDM-integrating products.*
2. **M4.** In `MILESTONES` or not. Legacy lists it in
   `INTEGRATION_FOR_SANDBOX_MILESTONES` and gives it date columns; NHA's
   current documents tag nothing with it. **Blocks D6 only.**
3. **Milestone DAG.** Enforce `m2→m1`, `m3→m1`, `health_locker→phr` in
   `clean()`, or not. Unsourced in both NHA documents (§7), so this is a
   deliberate call, not an inherited rule. Put all the rules to NHA together.

## 10. Build order

Each step shippable.

1. **E1–E4** with tests — the engine delta, nothing ABDM-specific.
2. **Models** — `MilestoneGrant`, `ProvisionedResource`, `NotificationLog`,
   `Sandbox` re-point; Organisation fields.
3. **Domain fixes D1–D6** — small, sourced, independently verifiable.
4. **`integrations/`** — the riskiest port. Adapters and ports first behind
   the existing fakes, then re-anchor the trigger onto E1.
5. **Predicates + console surfacing** — DHIS eligibility and compliance read
   `MilestoneGrant`.

## 11. Dropped

- `sandbox/workflow/` entire — engine, `TransitionSpec`, `ActorKind`, guards,
  registry, `WorkflowTransition`, `WorkflowReview`
- `sandbox/applications/` models — `Application.state`, `round`,
  `ApplicationState`, `RESTING_STATES`
- `sandbox/console/` — `experience`'s admin views replace it
- `11-workflow-rewrite.md` as a build plan: the verb engine, the cycle/lock
  design, permission-minting-at-migrate, and the ~61-file blast radius

Surviving from `11` and credited above: §7 (provisioning is not workflow, and
the attempt/resource split), §8.1 (WASA travels with the exit), §8.3
(post-approval updates), §10 (the decision-time ceiling), and the
registry-key pinning test.
