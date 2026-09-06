# 12 — Rebuilding the ABDM Sandbox Portal on `experience`

Status: in build (2026-09-06). Steps 1–3 committed, step 4 written and under
review. Replaces `12-experience-adaptation.md`, `13-reconciliation.md` and
`14-repo-port.md`, which are superseded in full: three documents correcting
each other, where two of them were partly wrong.

Everything below is either **sourced** — quoted from NHA, or read from legacy
code and legacy data, with the source named — or **decided**, with the
reasoning kept. Nothing is inherited on trust.

Figures from the legacy database are deliberately not reproduced here. Where a
conclusion rests on one, it says so and names the table; re-run the query
against a local restore if it needs confirming.

---

## 1. What we are building

A portal for integrators applying for ABDM production access, and for NHA to
review those applications.

**The base is this repository**, with `ohcnetwork/experience`'s code copied in.
`experience` already carries the thing the earlier plans were going to build
from scratch: a declarative form registry, an applicant workspace, an NHA
console, versioned submissions, query threads, an append-only event log, and
per-application permissions. What survives from this repo is the ABDM domain
and the external integrations.

**The shape.** One `ApplicationInstance` per request. Milestones, security
evidence, conformance and the exit claim are **forms on it**; every filled form
is an `ApplicationFormSubmission`; the decision lands in
`ApplicationInstance.outcome`. A second application a year later is a second
instance of the same type.

**The registry is code, not data.** A form definition is a Python class whose
only tie to the database is a string:

```
CODE (registry)                                DATABASE
ApplicationDefinition       .key ───────────→  ApplicationInstance.application_type
  ├─ .statuses              .key ───────────→  ApplicationInstance.status
  ├─ .roles                 .key ───────────→  ApplicationAccess.role_key
  ├─ .forms → ApplicationFormDefinition
  │             .key ──────────────────────→  ApplicationFormSubmission.form_key
  └─ .actions → ApplicationAction .key ────→  ApplicationEvent.action_key
```

Legal values live in the registry, never in a database CHECK. Renaming a key
orphans its rows, so a registry test pins the known keys.

### 1.1 Two shape decisions everything else rests on

**Review is application-level.** The decision lands in
`ApplicationInstance.outcome`. `MilestoneGrant` rows are **not** written from
it: production access is one application-level decision and does not enumerate
milestones. They follow the **reviewer's verification** of the
`milestone_declaration` and its bundled WASA certificate (§6 D8): the
declaration is the applicant's own attestation and the WASA is a security
audit, so neither earns anything until NHA has verified it. Once both are
verified the application is approvable for production access. Milestones are self-declarations; the exit review is the single gate.
An earlier design (`11-workflow-rewrite.md`, retired) put review on each
`FormSubmission` — this departs from it consciously. It is what keeps
`ApplicationFormSubmission` untouched, and is the largest single saving here.

**No root container.** Nothing sits above `ApplicationInstance`. A parent would
need its own status, permissions, access and audit — and `ApplicationAccess`,
`ApplicationQueryThread` and `ApplicationEvent` all FK to `ApplicationInstance`,
so queries and audit would either fragment across children or move up with it.
That is the engine rebuilt one level higher. One instance instead;
`MilestoneGrant` carries the fact that outlives it.

**Counts, so the levels are not confused.** One *type* today
(`abdm_production_access`) → one *instance* per vendor request → up to nine
*submissions* per instance today, **eleven once D8 and D9 add their forms** →
several *revisions* per submission.

Legacy's scale is tens of thousands of applications and thousands of exits.
`ApplicationAccess` is keyed on the instance — the level that grows without
bound — which is why §5 puts NHA's authority somewhere else.

---

## 2. Sources

Read directly, not inherited.

| source | how | what it settled |
| ------ | --- | --------------- |
| `sandbox.abdm.gov.in/sandbox/v3/faq` | browser — it is a JS app, `curl` returns an empty shell | the milestone descriptions |
| `sandbox.abdm.gov.in/sandbox/v3/new-documentation`, all 16 tabs | browser | M4 exists; the exit process; the M1 government matrix |
| *Commonly Asked Questions — Integrator Guide* v1.4, 20 Nov 2025 | PDF | the exit gate. It also carries a **mandatory-HI-types-per-participant-category** matrix (HMIS → all 8, Pharmacy → Invoice mandatory, PHR/Locker/Health Worker → all 8, …) not reproduced here — §8.3's predicates need it, so read it there |
| the milestone → Keycloak role map | supplied by NHA, 2026-09-05 | §3's role column |
| legacy Java source (`abdm-sandbox/`) | read | the M1/PHR gate, the NHCX enrolment/exit split, the permission model |
| the legacy database | read locally; figures not reproduced here | `13-legacy-import.md` |
| **v3 specification** — [artifact](https://claude.ai/code/artifact/ddedf004-38ab-48ec-afd6-b0b13be7f31c) | our own, written before this plan | the behaviour: statuses, roles, gates, the nine field blocks, the five applications |
| **v3 data model** — [artifact](https://claude.ai/code/artifact/3cee75e5-af9c-4c5e-99a0-33dbc4e1bfc7) | our own, derived from the specification | the 24 tables §4.4 answers |

**Both artifacts predate this plan and are superseded where they disagree with
it.** The data model still draws seven milestones, `ProvisionedResource` with an
organisation FK, and a `review_role`-shaped access model; the specification
still lists runtime role editing as something not built (§5.2). Read them for
the behaviour they describe, not as the current design.

---

## 3. The domain

### 3.1 Four milestones

| | milestone | prerequisite | Keycloak roles |
| - | --------- | ------------ | -------------- |
| M1 | ABHA creation, capture and verification | — | `healthId`, `HidAbhaSearch` |
| M2 | HIP — link records to ABHA, consented sharing | none stated | `hip`, `HIP_PAYER` |
| M3 | HIU — consented access to records | none stated | `hiu`, `HIU_PAYER` |
| M4 | NHPR — native professional and facility registration | **M1, M2 and M3** | `hp_id`, `DIGI_DOCTOR`, `hfr`, `bridge` |

The FAQ says *"There are mainly three different Milestones"*, but
`?doc=NHPR` is headed **"What is Milestone M4?"** and states *"Integration of
NHPR functionality in the healthcare application/software is milestone M4"* —
so four. The same page is the only place any ordering is stated: *"After an
entity successfully completed integration of ABDM milestones, M1, M2, and M3,
integration for M4 can be initiated."*

**M2→M1 and M3→M1 are not stated anywhere and are not enforced.** Standing
rule: what the documents do not say, we do not enforce.

**Not milestones:** PHR, health locker and NHCX. NHA's Test Cases page numbers
M1–M4 as rows 1–4 and lists *"PHR and Locker V3 Test Cases"* as row 5, outside
the numbering. PHR and health locker are `ABDM_ROLES`; NHCX is a separate
programme run with IRDAI.

The role map is sourced and confirms both legacy's map and the v3
specification's own role column, neither of which previously had a source. All ten
names already exist in `FAKE_KEYCLOAK_REALM_ROLES`.

Because all four milestones owe roles, `MilestoneGrant` needs no "none owed"
state — the case cannot arise. Role-attachment **failures** go to
`ApplicationEvent` rather than a column on the grant.

One more fact worth not rediscovering: registering at `hspsbx.abdm.gov.in`
yields a facility ID, and *"the same facility ID"* serves both roles — HIP for
M2, HIU for M3. It is a setup step, not a milestone.

### 3.2 The exit process, as NHA documents it

`?doc=SandboxExit`, four steps:

| step | what | detail that matters |
| ---- | ---- | ------------------- |
| 1a | Functional testing | one of **9 named NHA-empanelled agencies**, chargeable, *"should not exceed beyond 7 working days"* |
| 1b | **Internal demo by NHA** | FT reports go to NHA first; *"No FT report will be accepted if the report is not in the approved format"* |
| 2 | WASA | STQC **or** CERT-In empanelled; the artefact is a **"Safe-to-Host" certificate** — same thing |
| 3 | **HTC approval** (Health Tech Committee) | exit form + artifacts, then a *second* demo to HTC |
| 4 | Production access | NHA emails client-id and secret |

Four consequences:

- **Two demos, not one.** Only the *internal* demo gates submission. The HTC
  demo is a review step, so it belongs in the review workflow, not in
  `SubmitApplication.extra_availability`.
- **The exit artifacts are exactly four**: FT certificate & reports, WASA
  certificate, Undertaking, GSTIN certificate.
- **The hard copy is real** — *"hard copy of duly signed 'Undertaking' form
  must be sent via courier/speed post"* — so a received-date must be
  recordable by a reviewer, not the applicant.
- **M1 must be on V3 APIs**: *"no implementation is accepted for Exit process
  if the milestone M1 is done using V1/2 APIs"*, migration deadline
  31-Jan-2025.

**M4 runs a different evidence track**: functional testing by NHA's own NHPR
team rather than an empanelled agency, plus a video recording of the workflow
and a security audit *with* a VAPT report.

**One deliberate departure.** NHA emails the production secret. We show it once
in the portal instead. That is a change we are choosing, not a requirement we
inherited.

### 3.3 Gates, confirmed against legacy

`SdLoginServiceImpl:1338-1345` enforces the NHCX gate in two separate checks —
M1-or-PHR production-approved, **and** a production client ID issued. Both
throw the same error constant, so a missing client ID reports *"You are not yet
compliant with Milestone 1 or PHR"*. We split them into two messages.

**NHCX enrolment and NHCX exit are different things.** Enrolment has no review
in legacy — only `updateNhcxExitStatus` has a decision verb, and every reviewed
endpoint is named `…NhcxExit…`. Going live means a production application
declaring the NHCX milestone. Whoever writes the NHCX definition should not
model enrolment as a reviewed application.

---

## 4. The model

### 4.1 Unchanged — `experience`'s engine

`ApplicationInstance` · `ApplicationFormSubmission` · `ApplicationAttachment` ·
`ApplicationAccess` · `ApplicationQueryThread` / `Message` · `ApplicationEvent`

`ApplicationFormSubmission` is richer than the v3 data model asked for:
`submission_number` + `revision` + a partial-unique `is_current`, plus
`valid_until`, which is exactly the WASA expiry the exit gate needs. An *edit*
raises `revision`; a *resubmission* raises `submission_number`.

### 4.2 Added

| model | why |
| ----- | --- |
| `MilestoneGrant` | organisation-scoped, durable. `organisation` · `milestone` · `granted_by → ApplicationInstance` · `granted_at` · `roles_attached` · `roles_attached_at`. A later application reads it rather than re-deriving from forms. Written from D8's `milestone_declaration` submission, not from the approval — §1.1. **The model has landed; its writer arrives with D8** — a `VerifyMilestoneDeclaration` form action following `VerifySecurityEvidence`'s pattern |
| `NotificationLog` | `event → ApplicationEvent` · `recipient` · `channel` · `template_key` · `status` · `sent_at`. The v3 model also wanted `body_as_sent` and `resent_from`, to make "a resend reuses the original wording" enforceable — that is a service-layer guarantee a test can hold, so the columns are dropped |
| `ReviewRole`, `ReviewRoleAssignment` | §5 |
| `ApplicationEvent.is_internal` | **new** — not to be confused with `ApplicationQueryMessage.is_internal`, which already exists and answers §4.4's `Opinion`. v3's "hidden from the applicant" had nowhere to live. A flag, not a projection filtered by `kind` — otherwise one internal note of an otherwise public kind cannot be hidden |

**Append-only weakened, deliberately.** The deleted `audit` app carried a
migration running `REVOKE UPDATE, DELETE ON … FROM CURRENT_USER`;
`ApplicationEvent` enforces the same rule in Python, by raising in `save()`. We
took `ApplicationEvent` as it stands and did **not** port the revocation.
Recorded rather than glossed: the guarantee moved from one the database
enforces against every client to one the ORM enforces against ours, so a raw
`UPDATE` would now succeed. Revisit if anything outside Django is ever given
write access.

### 4.3 Kept from this repo

`ProvisionedResource` already exists in `sandbox/integrations/models.py` and is
**application-scoped with no organisation FK**; its states are `ACTIVE /
DISABLED / FAILED / ORPHANED`, and `NOTIFICATION` is deliberately not a system
because it is sent through, not provisioned into. `complete_provisioning`
already implements the rule that matters — *"Only the ledger decides this —
never 'the chain got this far'"*.

`Sandbox` is kept and re-pointed from an `Organisation` OneToOne to an
`ApplicationInstance` FK. It is the **attempt** record that
`ProvisionedResource` cannot be: without it, "the run failed before creating
anything" has no row to live on. Drop its `facility_name` and
`is_facility_empty` — they describe a Care facility, not an attempt.

### 4.4 What did not become a table

The v3 data model named 24 tables. The rule applied to each: **a requirement is
met by a form, an audit event, or a column before it is met by a table.**

| asked for | answered by |
| --------- | ----------- |
| `Opinion` | `ApplicationQueryMessage.is_internal`, which **already exists** — an internal message *is* the opinion |
| `Verification` | `VerifySecurityEvidence`, which already exists: a reviewer-only action stamping `verified_revision`, so staleness is a revision comparison rather than stored state. **Replicate it for the other three exit artifacts** — §3.2's four — since an action takes `cleaned_data`, which is where §3.2's hard-copy received date is collected |
| `BlockAnswer` + `BlockConfirmation` | fields on `Organisation`, plus the snapshot that `ApplicationFormSubmission.data` already keeps |
| `MilestoneDeclaration` | a form — §6, `milestone_declaration` |
| `Correction`, `CredentialEvent` | `ApplicationEvent` rows — with the weakening §4.2 records. A correction is an NHA edit *after* a decision, and `editable_statuses` is `{draft, changes_requested}`, so it cannot be a form edit: it needs its own action available in `approved` |
| `Decision` | `ApplicationInstance.outcome` (JSON — the typing loss is accepted) |
| `ExportRecord` | deferred: the console has no export feature to record |
| `VerificationCode` | `sandbox/otp/`, 129 lines, already sending through the `NotificationGateway` port. **Mobile only** — allauth owns email (`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`) |
| `StaffRole` | §5 |

### 4.5 The individual applicant

A large share of legacy applicants are one person rather than a company —
`sd_login.application_type = '2'` — and they are a reviewed population, not
abandoned signups: they reach `sd_status` and are decided like anyone else.
They saw a much shorter form (user details, solution type, intent), and legacy
collected no entity for them at all: `entity_type` and GST are blank across
that population.

**They get a one-person `Organisation`, named after the person, with
`nature_of_entity = INDIVIDUAL`.** Not a nullable `ApplicationInstance
.organisation` — that FK is assumed non-null by `visible_to`, `ApplicationAccess`
and every console query, and making it optional would spread the special case
across all of them.

The evidence is that legacy already did this, just later and less visibly. It
substituted at the wire rather than in the data
(`WorkflowServiceImpl.java:277-288`):

```java
if (INDIVIDUAL_APPLICATION_TYPE_ID.equals(sdLogin.getApplicationType())) {
    name = sdLogin.getName();          // the person
} else {
    name = sdLogin.getOrganization();
}
name = name.replaceAll("[^a-zA-Z0-9]", " ").trim();
String entity = INDIVIDUAL_APPLICATION_TYPE_ID.equals(...) ? "NA"
                                                           : sdLogin.getTypeOfApplication();
```

So Keycloak and the bridge registry have always received the person's name in
the organisation slot. Holding it as an `Organisation` row produces the same
outbound payload with no `if individual` anywhere in `integrations/` —
`provision_keycloak` already sends `organisation.display_name`.

Legacy carried this on a separate `application_type` code and left
`entity_type` blank. We fold it into `nature_of_entity` instead: one fact, one
column, and the shorter form becomes a predicate on it rather than on a second
field that can contradict it.

The cosmetic cost is people appearing in a vendor listing, which
`listing_hidden` already exists to answer. What legacy's name handling means
for the importer is in `13-legacy-import.md` §4.

### 4.6 Migration

Legacy is reshaped into this design, not copied into it: the importer builds an
`Organisation`, an `ApplicationInstance`, an `ApplicationFormSubmission` per
form, the grants, and a `ProvisionedResource` cross-referencing the Keycloak
client that already exists. Nothing in the result is described by a legacy
identifier, which is why no `legacy_sd_id` column exists (§8.3) — the key lives
in a mapping table the importer owns.

`13-legacy-import.md` has the whole of it: the table map, the field mappings,
the repeat-applicant rule, and what is still open.

---

## 5. Access control

**Authority is granted, never flagged.** Permission key → role → grant, with a
subject, a scope and a role.

### 5.1 Two sides, two mechanisms

| | who | mechanism |
| - | --- | --------- |
| **vendor** | the applicant's team | `ApplicationAccess` — per instance, `role_key` from the definition. The owner's row is written by `create_application`; teammates are granted |
| **NHA** | reviewers and decision makers | `ReviewRoleAssignment` — standing, portal-wide, no per-application row |

The vendor side needs a per-instance grant because *which applicant role* a
colleague holds is genuinely per application. The NHA side must not: legacy's
integrator accounts number in the tens of thousands, and a row per reviewer per
application was never going to work.

`ApplicationAccess` therefore means exactly one thing: **who on the vendor's
team may do what to this application.** Its platform half — the `"platform"`
branch of `assignable_roles`, `MANAGE_REVIEW_ACCESS`, and the reviewer side of
the access workspace — is retired.

### 5.2 Permissions are code, roles are data

The v3 specification ruled out runtime role editing: *"Roles are defined in the
system and changed by release. The old screens for editing them are the source
of several of its access problems."*

That concern is partly earned. Reading legacy's live permission data found two
real failures:

- **The action verb is decorative.** `CustomPermissionEvaluator` never looks at
  the `'read'` / `'write'` argument — `hasPrivilege` takes only the module
  list. So `IS_AUTHORIZED_TO_GET_STATUS` and `IS_AUTHORIZED_TO_CHANGE_STATUS`
  name the same seven modules and differ only in a word that is discarded.
  `Role_Admin_view` can therefore change application status despite its name.
- **A role may reference nothing.** `User_view` has 14 users and no
  `mst_privilege` row, so `getPrivilegeBasedOnRoleId` returns null and the
  evaluator dereferences it. Those users get a 500, not a 403.

**What is *not* wrong, despite appearances.** The module list in the annotation
has stray leading spaces and the database's casing differs from the code's —
but the overload a two-argument SpEL call actually routes to maps
`module.toUpperCase().trim()` over the split, and `GET_MODULE_NAMES_BY_MODULE_ID`
is `Select UPPER(mm.module_name) …`. Both sides are normalised, so those match
fine. The untrimmed four-argument overload exists but nothing in the source
reaches it. An earlier draft of this plan claimed four failures on the strength
of reading the wrong overload; it is recorded here because the mistake is
instructive — the *shape* of the code invites the conclusion, and only checking
which method Spring dispatches to disproves it.

**Neither surviving failure is about roles being editable.** One is a
permission model whose verb is unenforced; the other is a role that can exist
without permissions at all.

`experience` does not work that way — permission keys are declared in code and
referenced directly (`ApproveApplication.permission =
permission_keys.APPROVE_APPLICATION`). So the line to hold is not "roles are
code" but:

> **Permission keys stay in code. Roles become data. A role may only bundle
> keys the registry declares.**

An administrator can create roles, choose their permissions and assign users —
everything legacy's screens did — and cannot invent a permission, because the
picker is populated from the registry and `clean()` rejects unknown keys.

Both surviving failures become unrepresentable. There is no action verb to
ignore: the permission *is* the granularity, so a role that may view and not
approve says so by holding one key and not the other. And a role holding no
permissions is valid, expressible and harmless — §5.4's `user_view` — rather
than a null dereference.

| model | fields |
| ----- | ------ |
| `ReviewRole` | `key` · `name` · `description` · `permissions` · `is_active` |
| `ReviewRoleAssignment` | `user` · `role` · `granted_by` · `created_at`, unique per pair |

`get_effective_access` resolves the instance grant, then **unions** the
standing permissions onto it — so someone who is both an integrator and a
reviewer keeps both. `visible_to` opens on holding `VIEW_APPLICATION`, **not**
on holding a role: otherwise a role with no permissions would see every
application in the portal, which is the opposite of what it means.

One role per user was a legacy limitation from `sd_login.role_id` being scalar.
The assignment table is many-to-many, so "HTC plus UHI observer" needs no
invented combined role.

### 5.3 Seeded roles

`review_observer` (view, view queries) · `reviewer` (+ review, raise and
resolve queries) · `decision_maker` (+ approve, reject). These are the sets the
three `RoleDefinition`s carried before they left the registry, less
`MANAGE_REVIEW_ACCESS`, which §5.1 retires.

### 5.4 Legacy's roles

Legacy's eight `mst_role` rows map onto §5.3's three, plus an empty `user_view`
and a `super_admin`. Two are blocked by §5.5. The mapping, and the evidence
that `Role_Admin_view` has never decided anything, are in
`13-legacy-import.md` §5.

### 5.5 The one deferred constraint

`UHI Application` and `nhcx` are **scoped observers** — one queue each, no
decision rights — and three real people hold them. A portal-wide role cannot
express that, and migrating them as global observers would hand them visibility
they do not have.

They are not blocked on us: UHI and NHCX have no `ApplicationDefinition` yet,
so there is nothing to scope *to*. **When the second application type
registers, `ReviewRoleAssignment` gains a nullable `application_type`.** That is
one column on a grant — which is why this is a grant and not a field on `User`.

---

## 6. Engine and domain changes

**Engine** (`experiences/`), two changes; everything else untouched:

| # | change | why |
| - | ------ | --- |
| E1 | `ActionResult.effects: tuple = ()` and `FormActionResult.effects`, both run via `transaction.on_commit` — in `perform_application_action` and `perform_form_action`. The form path is what a verification writes a `MilestoneGrant` from (§1.1) | the only write-path change. Nothing could otherwise write `MilestoneGrant` or enqueue provisioning on approve. Additive — a definition declaring none behaves exactly as before, and effects run **after** commit so one never sees a rolled-back write |
| E2 | `WithdrawApplication`; `WITHDRAW_APPLICATION` into `COMMON_PERMISSIONS` and the owner role | the permission key and the `withdrawn` status both existed with no action reaching either |

**ABDM domain**, each settled by §3. *(These are renumbered against the
retired documents: what was D2 there is D1 here, and D1 is D2 — relevant only
when reading older commit messages.)*

| # | change |
| - | ------ |
| D1 | exit gate — FT evidence · an unexpired `wasa` certification · the **internal** NHA demo. The HTC demo is a review step. The fields exist already: `ConformanceEvidence` carries `functional_testing_agency`, `functional_certificate_number`, `demonstration_date`, `demo_recording_url`; WASA is a `security_certification` submission; `TechnicalReadiness.production_callback_url` is the callback NHA requires — *"The Callback URL must be specified when submitting the Exit Form"* |
| D2 | health information types 6 → 8: add `HealthDocumentRecord`, `Invoice` |
| D3 | drop `wasa_certificate_number` from `SecurityComplianceForm` — it duplicates the copy that carries expiry and renewal |
| D4 | decision-time ceiling on `ApprovalForm.approved_milestones`: narrow to what was declared |
| D5 | `ABDM_ROLES` gains `hrp` |
| D6 | `MILESTONES` becomes `[m1, m2, m3, m4]` |
| D7 | enforce `m4 → m1 + m2 + m3` in `clean()`. **The only prerequisite there is** |
| D8 | a `milestone_declaration` form owning `milestones` and per-milestone start/end dates, split out of `integration_scope` — §6.1 |
| D9 | an `nhpr_evidence` form, `is_applicable` when M4 is declared: video, security audit **and** VAPT |
| D10 | government applicants declaring M1 must additionally cover Aadhaar biometrics and offline demographics |
| D11 | record `demonstrated_on_current_apis`; an M1 graduation on V1/V2 APIs is not acceptable |

### 6.1 Why `milestone_declaration` is its own form

`IntegrationScopeForm` already carries roles, milestones, client id, facility
ids, information types, integration approach and connector name. Adding eight
conditional date fields makes a fifteen-field form where most fields are
conditional on checkboxes inside it.

This is **one form for all milestones**, not a form per milestone — that was
rejected, and stays rejected, because per-milestone definitions were only ever
justified by per-form review, which §1.1 removes.

More importantly it is what makes D9 possible: `nhpr_evidence` gates on
`m4 ∈ milestones`, and a form can only be gated on a milestone if milestones
have a `form_key` of their own to read from — the pattern
`HealthLockerOperations` already uses.

Date fields are built in `__init__` looping `MILESTONES`, so a fifth milestone
costs nothing. `IntegrationScope` sheds `milestones`, and the sourced
`hip → m2` / `hiu → m3` rules move with them.

---

## 7. The external integrations

`sandbox/integrations/` is the usable part of this repo and is not redesigned:
Keycloak, WSO2, HIE-CM and the notification gateway behind `ports.py`
protocols, a `settings.INTEGRATION_PORTS` registry, and 400 lines of fakes that
let the whole portal run offline.

Only its **wiring** changes, because it talks to two things that are deleted:

| today | becomes |
| ----- | ------- |
| `hooks.py` — `register_hook("provisioning_chain", …)` | an entry in the approve action's `effects` |
| `hooks.py` — `register_hook("deprovisioning_chain", …)` | the same on reject and withdraw |
| `services.py`, `tasks.py` — `transition(...)` | a status write plus an `ApplicationEvent` |
| `Application` / `ApplicationState` | `ApplicationInstance` / `Sandbox.status` |

**There are no registry statuses for provisioning, deliberately.** The ABDM
definition has eight — `draft`, `submitted`, `under_review`,
`changes_requested`, `revision_submitted`, `approved`, `rejected`,
`withdrawn` — and none is a provisioning state. Adding one would split
application status from attempt status across two places. Provisioning state
belongs on `Sandbox`, whose enum is already `requested / provisioning / ready /
failed`.

**Deprovisioning already exists** — a reverse chain on rejection and
withdrawal. E2's withdraw action should reach it rather than invent one.

**Both retries lost their permission check in step 3.** `retry_provisioning`
and `retry_deprovisioning` rode `transition()` and `get_workflow(...)
.permission_for(...)`; unplugged, they enqueue their chain directly. Step 5
returns them as registry actions with a permission, which is also what puts a
retry back in the console.

### 7.1 Couplings that survive an import purge

References that are **strings or attribute lookups** do not fail at import, so
they stay dormant until the code runs. All of these come due together:

| where | what |
| ----- | ---- |
| `notifications/hooks.py` | `reverse(..., kwargs={"external_id": ...})` — `ApplicationInstance` has no `external_id`, and every `experiences` route keys on `<str:reference>` |
| `notifications/hooks.py` | `application.applicant` — it is `created_by` now |
| `notifications/hooks.py`, `integrations/tasks.py`, `credentials.py` | `application.product` — **`Product` is abandoned**; use `application.organisation`, and `organisation.display_name` where it named a Keycloak client, WSO2 application or HIE-CM bridge |
| `integrations/selectors.py` | `CREDENTIAL_STATES`, four state **strings** written deliberately to avoid an import cycle, and `application.state == "PROVISIONING"` |

`notifications/hooks.py` registers **five** hooks, and `notify_provisioned` is
not an `effects` entry: it fires on a transition the chain raises itself, so it
becomes a direct call from `complete_provisioning`.

---

## 8. Where the build has got to

| step | state |
| ---- | ----- |
| 1 · delete the machinery | **done** — `63b5e2d`. Five apps, seven test modules, the seed command, 33 templates, both lint contracts |
| 2 · copy `experience` in, rename, strip the Care plugin | **done** — `552692c` |
| 3 · settle settings, unplug the chain, reset migrations | **done** — `1ce4282`. 639 tests green. Restored the six `.txt` notification bodies step 1 deleted — they were counted as zero because the count globbed `*.html`, and twenty tests failed on it |
| 4 · engine delta + access control | **done** — `6094eb0`. E1, E2, §5 in full |
| 5 · plug in | **done** — `b9c102b`, `ac4a410`, `108b88a`. §7 wired onto `effects`; `Sandbox` → `ProvisioningRun`; §7.1's couplings; retries back as registry actions; the deleted test modules restored; `test_chains.py` out of the gate and verified against real WireMock. 751 tests green, 1 skip |
| 6 · re-apply the design | not started — `MilestoneGrant`, `NotificationLog`, `ApplicationEvent.is_internal`, the `VerifySecurityEvidence` replication for the other three exit artifacts (§4.4), a `Correction` action reachable in `approved` (§4.4), D1–D11, and the fields §8.3 names |

The suite needs Postgres, and the counts above were run against a local server
rather than the project's Docker one: `POSTGRES_HOST=localhost USE_DOCKER=no`
with a `debug` role, so `just pytest` will disagree if Docker is down.

`tests/integrations/` additionally needs WireMock, which is compose-profiled and
therefore absent by default:

```
docker compose -f docker-compose.local.yml --profile wiremock up -d wiremock
```

Without it those eighteen tests skip; with `WIREMOCK_REQUIRED=1`, as CI sets,
they fail instead — the distinction exists because a silent skip and a pass are
otherwise the same thing. A container left from an earlier compose run can hold
a stale network id and refuse to start; `--force-recreate` on that one service
clears it.

### 8.1 Decisions taken during the port

Executed, and recorded because the preamble promises the reasoning is kept.

- **The django-ninja API does not come along.** `config/api.py` mounted one
  router whose five endpoints all filtered to `request.user` — a self-only
  read of your own name and email, duplicating the profile view. Dropped with
  `django-ninja` and `django-cors-headers`.
- **`TIME_ZONE` stays `Asia/Kolkata`**, against `experience`'s `UTC`. Three of
  its event tests asserted `"3:00 p.m. UTC"` and now assert IST — which is the
  bug their own docstring says they exist to catch, for an Indian audience.
- **`theme/` was a toolchain swap, not a directory replace**:
  `django-tailwind-cli` (CLI binary, no Node) gave way to `django-tailwind`
  (npm `static_src`), and the arriving `theme/` lives at the **repo root**,
  outside the package — so the bulk copy would have missed it.
- **The migration reset was safe** because the only database is the local
  Docker one, reset and reseeded rather than migrated; legacy is a separate
  system. A production compose file and release workflow exist, so a
  production path is *configured* — if that ever changes, the reset is not
  repeatable.

### 8.2 Carried debts

- **Staff MFA is unenforced.** Replacing `users/` wholesale dropped
  `middleware.py`, which required TOTP for staff and verified contacts for
  everyone else. It cannot return until the mobile-verification field exists,
  so `STAFF_MFA_REQUIRED` currently guards nothing.
- **`programmes/abdm.py`** still imports the deleted `workflow`, harmless only
  because nothing imports it. Mine it in step 6 for the DHIS predicates, then
  delete it.
- **`catalog/selectors.py`** has no caller between steps 2 and 6. Do not let
  that fool anyone into deleting it.
- **`tests/`** at the repo root carries a `collect_ignore` list; the list
  reaching empty is what finishes it. `test_credentials_panel` holds the
  "secret appears in no audit row" assertion and must survive its rewrite.

### 8.3 The fields step 6 re-applies

Replacing `users/` and `organisations/` wholesale (§8, step 2) was the right
call — `experience`'s are larger and carry the UI — but it dropped columns this
repo had. Port them forward from `552692c^` rather than re-deriving:

**`Organisation`** — **done**, migration
`0004_organisation_abdm_identity_fields`: `category`, `nature_of_entity`,
`mobile_verified_at`, `listing_hidden`, and the LGD
`lgd_state_code` / `lgd_district_code` that `catalog/` exists to serve, which
un-skipped `catalog/test_selectors.py`. `NatureOfEntity` and
`OrganisationCategory` come back with their CHECK constraints, both admitting
`""` because onboarding collects them later.

Three of the fields this section originally named were dropped, each for a
reason worth keeping:

- **`is_individual`** folded into `nature_of_entity = INDIVIDUAL` — §4.5.
- **`email_verified_at`** — allauth owns email verification
  (`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`) and §4.4 makes `sandbox/otp/`
  mobile-only. An organisation-level email flag would compete with it.
- **`legacy_sd_id`** — §4.6. Wrong cardinality on this model, and the
  migration reshapes rather than copies, so nothing in the result is described
  by it.
- **`sandbox_client_id` / `production_client_id`** — each would be a third home
  for a value two places already hold with clear owners:
  `ApplicationInstance.outcome["production_client_id"]` is what the reviewer
  recorded at approval, `ProvisionedResource.public_ref` is what Keycloak
  issued. A column on `Organisation` would have no owner, no rule for
  disagreement, and — since an org holds several applications, ABDM now and
  NHCX/UHI later — no way to represent more than one. They exist on legacy's
  `sd_login` because that one row *was* the org, the application and the
  credentials at once; we have already split that three ways. Add them only
  once someone names which of the three is authoritative.

**`users/`** gains back `middleware.py` (§8.2) and whatever of the dropped
`services.py` survives review.

**The predicates** — `covered`, `approved_types`, `dhis_enabled`,
`is_compliant` — are rewritten to read `MilestoneGrant` rows rather than the
old `ExitGrant` dataclass. Mine them from `programmes/abdm.py` before deleting
it.

---

## 9. Open

Everything the earlier documents held open is closed. What remains:

1. **`Super Admin`'s mapping** is described but not seeded — the seed creates
   three roles, not five. Add `user_view` and `super_admin` there, or leave
   them to the user-migration script.
2. **Legacy's `security_audit_trail` holds nothing.** Either the feature was
   never switched on or our copy excluded it. If the former, "legacy has no
   record of who decided" is worth telling NHA in its own right.
3. **Which action each exit notification hangs off.** `HOOK_TEMPLATES` carries
   three exit templates — `notify_exit_approved`, `notify_exit_rejected`,
   `notify_exit_sent_back` — named for a separate exit process that §1.1
   collapsed into one application. The earlier plan deferred this *to* this
   document; it is still unsettled, and step 5 cannot wire the effects without
   an answer.
4. **Two application-kind lists disagree** and nobody has reconciled them:
   `03-database.md`'s `SANDBOX|HCX|UHI|HIU|NHCX` against the v3
   specification's sandbox access, production access, NHCX enrolment, UHI
   registration, test login. HIU is a milestone, not a track; `HCX` may be a
   second programme or dead scope. It bites whoever writes the second
   definition.
