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
(`abdm_production_access`) → one *instance* per vendor request → **eleven**
*submissions* per instance: ten the applicant owes (one of which,
`health_locker_operations`, is conditional on scope) plus `production_details`,
which only the review team fills (§4.8) → several *revisions* per submission.

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

M4's four do not contradict `?doc=NHPR`'s *"HPID role, HFR role"*: `hp_id` and
`hfr` are those two, and the page names what must be assigned for an integrator
to begin, not the full Keycloak set.

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

**M4's extra evidence is not part of this process.** `?doc=NHPR` lists steps
that look like exit requirements — functional testing by NHA's own NHPR team, a
video recording of the workflow, a security audit *with* a VAPT report — but
they belong to a separate track. Read the verbs: *write to* two NHA addresses,
*share* the recording *with NHA*, and finally *"Assignment of required roles
(HFR/HPID) by NHA team"*. It is an email process the NHPR team runs, ending in
NHA attaching the roles directly.

The exit process on this page never mentions M4, VAPT or a recording, and the
legacy portal collects none of them — an M4 integrator files the same exit form
as everyone else. So M4 is declared, reviewed and granted exactly like M1-M3
here; the evidence behind it reached NHA another way.

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
| `ReviewRole`, `ReviewRoleAssignment` | §5 |
| `ApplicationEvent.is_internal` | **done** — not to be confused with `ApplicationQueryMessage.is_internal`, which already exists and answers §4.4's `Opinion`. v3's "hidden from the applicant" had nowhere to live. A flag, not a projection filtered by `kind` — otherwise one internal note of an otherwise public kind cannot be hidden. It closed a live leak: `VendorApplicationDetailView` and `AdminApplicationDetailView` share one mixin, so the applicant's timeline showed every event including NHA's. An action declares `internal_event` — the model field keeps the name `is_internal`, since it describes the row; `review_evidence` and both retries set it. **The rule for setting it:** the action neither moves the status nor was raised by the applicant. It is not derivable from permissions — `start_review` and `review_evidence` share `application.review` and differ on it (§4.9). Events written outside any action stay public, `provisioning.failed` deliberately among them: the applicant seeing a failed run is what lets them chase a retry that NHA never made, through the query threads that already exist |

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
| `NotificationLog` | `notifications.Message`, which **already exists** and carries every column asked for — recipient, channel, template_key, `state` for status, and BaseModel's timestamps — plus params, attempts, last_error and the provider's id. Only the `event → ApplicationEvent` link is absent; it is a column on `Message` if a view ever wants it, not a table. Legacy's own `notification_audit` has the same shape |
| `Opinion` | `ApplicationQueryMessage.is_internal`, which **already exists** — an internal message *is* the opinion |
| `Verification` | `VerifySecurityEvidence`, which already exists: a reviewer-only action stamping `verified_revision`, so staleness is a revision comparison rather than stored state. It needs to cover §3.2's four artifacts and the milestone declaration — but as **one review action, not five** (§4.7) |
| `BlockAnswer` + `BlockConfirmation` | fields on `Organisation`, plus the snapshot that `ApplicationFormSubmission.data` already keeps |
| `MilestoneDeclaration` | a form — §6, `milestone_declaration` |
| `Correction`, `CredentialEvent` | `ApplicationEvent` rows — with the weakening §4.2 records. **Not a bespoke action.** The one thing NHA actually corrects after a decision is the production client id, and §4.8 makes that a form whose `editable_statuses` is `{approved}`: a correction is then revision *n+1*, and `save_form_submission`'s `FORM_SUBMITTED` event is the audit row. Nothing else the decision records has a correction case — the client the sandbox issues is `ProvisionedResource.public_ref`, which no human types |
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

### 4.7 One review action, not five

A reviewer works through an application in one sitting: the milestone
declaration and the security audit backing it are read together, and §3.2's
four exit artifacts arrive as one bundle. Five separate verify actions is five
clicks for one judgement, and lets the parts drift — a milestone verified
against a WASA nobody looked at.

So `VerifySecurityEvidence` is replaced by a single application-level review
action stamping `verified_revision` on every submission it covers, in one
transaction, with one `ApplicationEvent`. `cleaned_data` still collects §3.2's
hard-copy received date.

Until it lands there is a real gap: `security_certification` has no verify
action at all, so `VerifyMilestoneDeclaration` can only gate on the WASA being
*submitted*. A reviewer can therefore verify milestones against a certificate
nobody has read.

---

### 4.8 The production client id

NHA's production realm issues it; this portal does not, and cannot verify it.
It is a **form the review team fills**, `production_details` — client id and
issue date — available in `approved` only, with `allow_updates = True` and
`required_permissions = {"edit": APPROVE_APPLICATION}` (§4.9).

It stays off the applicant's checklist because `view` follows `edit`, not
because it is out of scope — `is_applicable` is `True` for everyone, which is
the truth: the form belongs to the application, it is simply not the
applicant's to fill. Once it has a submission the applicant sees the value
anyway, because `submission_sections` includes any form that has one.

**Correction comes free.** A second save writes revision 2 and keeps revision 1
with `is_current = False`, and `save_form_submission` already emits a
`FORM_SUBMITTED` event carrying the actor and the revision. That is the whole
audit trail, with no bespoke action and no engine change.

Legacy is the argument for doing it this way. It captures the id on the exit and
NHCX enrolment screens, locks the field once it holds a value
(`disabled={... || getValues().ProductionClientId ...}`), and then needs a
separate screen — `PUT /v1/update/prodId/{id}` — to change it. That screen is
gated on the super-admin role *and* the username `admin`, and never calls
`auditLogger.logEvent`, though the applicant-details update beside it does. So
legacy can change a live integrator's production client id with no record of who
or when. **Nothing gates the value itself**: the search SQL has no status or
milestone predicate, both fields are `disabled={false}`, and `integrationLevel`
is fetched only to display. It is admin judgement, which is the only thing it
can be — there is no system here to check the value against.

It also gates NHCX enrolment (`SdLoginServiceImpl:1341`), which is the second of
the two checks §3.3 describes.

### 4.9 Two permissions, not one

Every form and action declares `required_permissions`, a mapping keyed by
capability, and asks it through `permission_for(capability)`:

| | forms | actions |
| - | ----- | ------- |
| may do it | `edit` | `perform` |
| sees it listed | `view` | `view` |

**`view` falls back to the acting permission when it is not stated**, so the
common case — see it iff you could do it — stays one entry, and only the two
exceptions spell themselves out: the form base declares `view =
VIEW_APPLICATION` because `applicant_viewer` watches its org's checklist
without being able to fill anything, and `production_details` declares only
`edit` so that `view` follows it.

**Why a mapping and not two fields.** `permission` meant *edit* on a form and
*perform* on an action — one name, two capabilities — and the listing rule
existed only for actions, inline in a view comprehension, and not at all for
forms. Keying by capability names the thing that was implicit. A flat
collection cannot do it: listing wants *any-of* and acting wants one
particular permission, so an all-of rule would make widening visibility
silently narrow editing.

**Why not an `audience` flag.** Because "platform" is not one audience —
reviewer, decision-maker and super-admin all sit inside it, and a
super-admin-only control listed as blocked to every reviewer leaks that it
exists. A permission composes at whatever granularity a case needs; a two-value
bucket does not.

**Declaring it replaces the mapping rather than merging.** Merging would have
let `production_details` keep the base's `view = VIEW_APPLICATION` while
narrowing `edit`, which is the exact leak being closed. The cost is that a
definition can drop its acting key, so `validate()` requires it and checks
every value against the catalogue — one loop where there were three scalar
checks.

`is_internal` is deliberately **not** folded in. It answers a third question —
whether the resulting *event* is hidden — and the answers differ: `approve` is
listed to NHA only, but its event is how the applicant learns the decision.

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
| D1 | **done** — `abdm/gates.py`, checked by `SubmitApplication`. exit gate — FT evidence · an unexpired `wasa` certification · the **internal** NHA demo. The HTC demo is a review step. The fields exist already: `ConformanceEvidence` carries `functional_testing_agency`, `functional_certificate_number`, `demonstration_date`, `demo_recording_url`; WASA is a `security_certification` submission; `TechnicalReadiness.production_callback_url` is the callback NHA requires — *"The Callback URL must be specified when submitting the Exit Form"*. `is_complete` already excludes an expired submission, so what the gate adds is that the certificate is a **Safe-to-Host** one: an ISO 27001 completes the form and does not satisfy NHA.

**Verified against legacy.** Its exit DTO marks two fields mandatory — the sd id and the self-declaration id — and nothing else, which is why a large minority of decided exits hold no evidence at all. But `GeneralUtils.validateFiles` names precisely these artefacts as mandatory and **has no callers**: the rule was written and never wired up. So this gate is not stricter than legacy intended, only stricter than legacy managed.

Two findings from that comparison: legacy modelled `wasa_file` and `host_file` as separate document types and `host_file` holds no rows, which confirms §3.2's "same artefact under two names". And legacy's intended set has a fifth member, `supporting_doc`, well populated in the dump; §3.2's list of four does not mention it, so the gate does not require it — a question for NHA rather than a guess |
| D2 | **done.** health information types 6 → 8: add `HealthDocumentRecord`, `Invoice`. Sourced from the Integrator Guide alone. Legacy has no health-information-type vocabulary anywhere — not in code, schema, or its portal's own UI bundle — so the six we started from came from `experience`'s scaffold rather than from ABDM, and the move to eight rests on that one document. The sandbox documentation never enumerates them — not on `?doc=MileStone_two`, whose "Health Record formats" is a heading with no list, nor on Test Cases, which is links to external sheets. The canonical definition is ABDM's consent-artefact HI Type enum, outside these pages |
| D3 | **done.** dropped `wasa_certificate_number` from `SecurityComplianceForm` — it duplicated `SecurityCertification`'s copy, which alone carries expiry and renewal, so the two could disagree about one certificate |
| D4 | **done, relocated.** The ceiling is `ReviewEvidenceForm.verified_milestones`, not `ApprovalForm`: §4.7 moved the judgement to the review, and grants follow it, so a ceiling applied later at approval would have had nothing left to narrow. The reviewer may drop what the evidence does not support, never add. `ApprovalForm` no longer names milestones at all |
| D5 | **done, and split.** `ABDM_ROLES` gains `phr` — the legacy portal's own UI carries it heavily and this list had only health locker, matching §3.1's "PHR and health locker are `ABDM_ROLES`". It also gains `hrp`, but on weaker ground: the current UI does **not** offer it. That came from `SandboxConstant`'s accepted-values whitelist and from historical `ndhm_role` values, so it is a legacy spelling the importer will meet rather than a role NHA offers today. Keep it for migration; drop it from the applicant's form if NHA confirms it is retired. Legacy has a fourth, `End User Applications (EUA)`, left out for want of evidence anyone selects it |
| D6 | `MILESTONES` becomes `[m1, m2, m3, m4]` |
| D7 | enforce `m4 → m1 + m2 + m3` in `clean()`. **The only prerequisite there is** |
| D8 | a `milestone_declaration` form owning `milestones` and per-milestone start/end dates, split out of `integration_scope` — §6.1 |
| D9 | **dropped, and the plan corrected.** An `nhpr_evidence` form was built and reverted: `?doc=NHPR`'s steps describe an email track the NHPR team runs, not the sandbox exit — §3.2. Gating submission on it would have blocked every M4 applicant on evidence the portal never sees. What survives is `ReviewEvidence.applicable_reviewed_forms`, since building it exposed that a conditional entry in `reviewed_forms` reads as permanently unreviewed and blocks approval for ever |
| D10 | **not a portal requirement.** `?doc=Milestone_one` carries the matrix, headed **"M1 Test Cases mapping by Role"** — it scopes what the empanelled agency's functional testing must cover for a government application, which owes Aadhaar biometrics and offline demographics where a private one owes neither. Legacy collects none of it: no Aadhaar, biometric, demographic or test-case column anywhere, in schema or Java. The portal takes the FT report as the evidence, which D1 already requires and `ConformanceEvidence.test_request_ids` already references. A capability checklist was built and reverted — the second time a documentation table was read as a form, after D9 |
| D11 | **done.** `demonstrated_on_current_apis` on the milestone declaration, required when M1 is declared and checked by D1's gate. Unlike D9 this is genuinely an exit rule — `?doc=SandboxExit` states it under step 1b, the internal demo. Asked only of an M1 declaration, since that is what the rule names |

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
| 6 · re-apply the design | **in progress** — §8.4 re-triages what is left of it; `MilestoneGrant`, `ApplicationEvent.is_internal`, §4.7's single review, §4.8's `production_details` form, D1–D8 and D11, §8.3's `Organisation` fields and staff MFA are all done; `NotificationLog`, D9 and D10 were dissolved rather than built, and so was the `Correction` action §4.4 asked for — §4.8 answers it with a form, whose revisions carry the correction and its audit. What is left: the view layer §8.4 describes and the eight modules in `tests/conftest.py`'s `collect_ignore`, the DHIS predicates (blocked on a solution-type concept), and deleting `programmes/abdm.py` once mined |

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

- **Staff MFA is enforced again**, as `StaffMfaRequiredMiddleware`. Confirmed
  as a policy choice, not an inherited requirement: legacy has OTP for contact
  verification and no TOTP, MFA or 2FA anywhere. This is a deliberate departure
  of the same kind as showing the production secret once instead of emailing
  it, kept because the console approves production access and `/django-admin/`
  can escalate accounts. Replacing
  `users/` wholesale dropped `middleware.py` and `STAFF_MFA_REQUIRED` guarded
  nothing. Only the staff half returned; the applicant half — OTP on both
  contacts — still waits on `User.email_verified_at` and `phone_verified_at`,
  which do not exist. `Organisation.mobile_verified_at` is a different thing:
  the organisation's contact number, not the user's own.

  Two consequences worth knowing. `UserFactory` activates TOTP for
  `is_staff=True`, because a staff account without it can reach nothing —
  `mfa=False` builds the account that gets redirected. And the seeders
  deliberately leave TOTP unset, so a seeded console account meets the
  middleware on first login exactly as production intends; the tests that
  reach the console set it up first.
- **`programmes/abdm.py`** still imports the deleted `workflow`, harmless only
  because nothing imports it. Mine it in step 6 for the DHIS predicates, then
  delete it.
- **`catalog/selectors.py`** has no caller between steps 2 and 6. Do not let
  that fool anyone into deleting it.
- **`tests/`** at the repo root carries a `collect_ignore` list; the list
  reaching empty is what finishes it. **Four of the eight are not rewrites** —
  §8.4 re-triages them.

### 8.4 The view layer that did not arrive

`experience` brought the shell: 150 templates covering the vendor side (list,
detail, form workspace, action workspace, query thread, access) and the console
(queue, application list and detail, organisations, events, tickets), each with
its htmx partials. Almost nothing is missing at the screen level. What is
missing is narrow, specific, and invisible until you go looking, because in
every case the layer *underneath* it was ported and tested.

**One template is a genuine orphan.** `components/secret_value.html` — a masked
value with reveal and copy controls — has no users. Every other unreferenced
template resolves by framework convention (allauth elements, error pages,
`users/user_detail.html` through `DetailView` naming).

#### The three gaps

**C7's credentials panel — built.** `sandbox/integrations/selectors.py` was a
presentation layer with no consumer: `credentials_for`, `provisioning_progress`
and `latest_run` had zero callers outside their own tests, so an approved
integrator could see neither their client id, nor their one-time secret, nor
whether provisioning succeeded. It now rides on the application detail page,
on **one route**: GET is the poll, and reveal and rotate are actions posted to
it. The route it replaced had four — a standalone page, a fragment, a reveal
and a rotate — which was four access rules to keep in agreement for two buttons
on one panel. `components/secret_value.html` finally has a caller.

Three properties are structural rather than asserted. There is **no console
counterpart**: no staff route to a secret exists in the URLconf at all, which
is a stronger claim than "staff are refused". **No URL a GET could burn the
hand-off on** — the single read is an action, not an address, so a prefetch, a
crawler or a restored tab lands on the poll; the older shape needed a redirect
to say the same thing. And the quickstart snippet
interpolates the client id but never the secret, checked against the template
*source* rather than a render, because the secret exists for one response and a
passing render proves nothing about the round trip where it does not.

The `developer` fixture is where the engine shows through: revealing needs both
an `Organisation` membership and an `ApplicationAccess` grant, because
`visible_to` asks for the grant — and rotation is refused on a third thing,
`Role.OWNER`.

**Provisioning progress.** Same selectors, same absence. `provisioning_progress`
returns one row per system in chain order *including the ones not reached yet*,
which is the display §7 was written for, and nothing renders it.

**The dashboard predates ABDM.** Its tiles were OHC Network's — a sandbox
facility, Care Basic certification, deployments — and its checklist asked for
two of them, both hardcoded `False` because nothing could ever set them. Those
are gone: the checklist is the two steps that are real (profile, team), and the
three tiles with them. What remains is the harder half — **the dashboard still
does not mention applications**, the one thing a vendor signs in to do. It
needs re-thinking against §3's milestones rather than patching, and
`test_dashboard.py` waits on that.

**The marketing pages are somebody else's.** `pages/home.html`,
`pages/about.html` and `account/signup.html` describe OHC Network's product,
not this one — *"One place for everyone who builds on Care"*, *"the Open
Healthcare Network's partner portal"*, *"Care Basic runs on school.nha.gov.in
today"*, and a footer link to `care.nha.gov.in`. The rename pass corrected the
product name and the words for NHA's own people, and deliberately stopped
there: substituting a noun into these sentences makes them wrong rather than
merely off-brand. They need writing, not renaming — what the portal's front
door should claim is a decision, and it is open.

#### Re-triaging `collect_ignore`

| module | verdict |
| ------ | ------- |
| `test_merge_production_dotenvs_in_dotenv` | **deleted** — the function it tested existed nowhere in the repo |
| `test_enrollment_wizard` | **deleted** — a multi-step draft wizard with product selection and back-navigation, a concept the engine replaced wholesale with `StartApplicationView` plus form workspaces, which are already tested |
| `test_route_gates` | **done** — 84 named URLs, 88 gate cases. It found the shipped htmx demo, the console access screen only a superuser could open, and that `is_superuser` did not open the console |
| `test_credentials_panel` | **done** — the panel was built to it; 13 tests |
| `test_dashboard` | after the dashboard is re-thought. Its wizard assertions go with `test_enrollment_wizard` either way |
| `test_navigation` | rewrite — it references `NAV_SECTIONS`, which no longer exists, and an application rail/switcher that may be obsolete |
| `test_stylesheet`, `test_template_syntax` | wait on the theme (§4.1) |

The order that follows from this: `test_route_gates` **(done)**, then the
credentials panel and its tests, then provisioning progress, then the dashboard
and its tests, then navigation. The two theme modules last.

### 8.5 The rename off OHC Network

The repo carried its origin in its names. `sandbox/ohc/` is `sandbox/staff/`
and its namespace is `staff:`; `is_ohc_team` is gone (§8.4);
`TicketMessage.from_ohc_team` is `from_staff_team`; `careui` is `ui`; the site
row is `localhost` / "ABDM Sandbox Portal"; and the wordmark, page title and
transactional copy name this portal and NHA rather than Care and the OHC team.

Migrations were **edited rather than added**, on the standing decision that this
branch squashes before it merges — the renamed column and the dropped flag are
in the initial migrations, not behind a `RenameField`.

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
- **`sandbox_client_id` / `production_client_id`** — two different ids, and
  neither belongs on `Organisation`. The **sandbox** client is
  `ProvisionedResource.public_ref`, what Keycloak issued and what
  `credentials_for` shows; legacy's equivalent is `sd_status.client_id`,
  generated at registration by `createClientId`. The **production** client is
  issued by NHA's production realm, which this portal does not run — legacy
  keeps it on `sd_login.production_client_id`, and no applicant-facing page ever
  asks for it: NHA staff type it on the exit and NHCX enrolment screens, once
  the integrator is already live. `ApprovalForm` used to collect it at the
  decision, which is earlier than the value can exist — provisioning is an
  *effect* of approval — and `_outcome_rows` then displayed the guess to the
  applicant beside the real sandbox one. It was removed; §4.8 owns where it
  lands instead. A column on `Organisation` would in any case have no owner,
  no rule for disagreement, and — since an org holds several applications, ABDM
  now and NHCX/UHI later — no way to represent more than one. They exist on legacy's
  `sd_login` because that one row *was* the org, the application and the
  credentials at once; we have already split that three ways. Add them only
  once someone names which of the three is authoritative.

**`ownership`** was missing from the list above and is now added
(`0006_organisation_ownership`) — legacy's `typeOfApplication`, part of the
company profile. It is **not** interchangeable with `nature_of_entity`: they
answer different questions, and in the dump most government *applications* come
from entities that are not government bodies — a private company building for a
state health department files one while remaining a Company. Nothing gates on
it today; it exists because the profile is incomplete without it.

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
