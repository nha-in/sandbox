# 13 — Reconciling the v3 data model with `experience`

Status: agreed 2026-09-05. **Corrects `12-experience-adaptation.md` §7 and D6**,
which are wrong about Milestone 4 and about whether NHA states a milestone
ordering. Everything else in `12` stands as written.

**The base is this repository.** `experience`'s code is copied into `sandbox/`
and everything unusable here is deleted — `12` §1 reads the port the other way
round and is wrong about it. The end state is the same; the repository we work
in is this one. What survives from `sandbox/` is the domain and the external
integrations (§9); what goes is listed in `12` §11.

This document settles the `Sandbox v3 Data Model` artifact (24 tables, derived
from the v3 behaviour specification) against the engine `12` adopts. The two
were written the same day from opposite directions and had never been read
against each other.

**The governing principle**, applied to every row of the v3 model: a v3
requirement is satisfied by a form, an audit event, or a column before it is
satisfied by a table. `experience` already carries versioned submissions, an
append-only event log, permissions and attachments; a new table has to earn its
place against those.

The result is that **`12` §4's model is unchanged** — `MilestoneGrant`,
`ProvisionedResource`, `NotificationLog`, the `Sandbox` re-point. Nothing is
added. Twenty of the v3 model's twenty-four tables either already exist in the
engine, become a form, become an audit event, or are dropped.

## 1. Sources

Read directly on 2026-09-05, not inherited:

| source | how | note |
| ------ | --- | ---- |
| `sandbox.abdm.gov.in/sandbox/v3/faq` | browser | a JS app — `curl` and plain fetch return an empty shell. Five tabs: General, Milestone #1/#2/#3, Integration queries |
| `sandbox.abdm.gov.in/sandbox/v3/new-documentation` | browser, all 16 tabs | footer reads *"Page last updated on: 29/07/2023"* |
| *Commonly Asked Questions — Integrator Guide*, v1.4, 20 Nov 2025 | via `12` §7 | the newer document |
| the milestone → Keycloak role map | supplied by NHA, 2026-09-05 | §2. Confirms legacy's map and the v3 specification's §1.4 role column, neither of which had a source |

**On the date conflict.** The documentation site is older (2023) than the
integrator guide (2025), and the guide tags nothing M4. But the M4 material is
live, is linked from three separate pages (`?doc=NHPR`, Test Cases, V3
Documentation), and names a current contact address. Treat M4 as live. The
FAQ's *"mainly three"* is best read as describing the common path, not an
exhaustive taxonomy — note the hedge in the word *mainly*.

## 2. Milestones — four, not three and not seven

`12` §7 concluded three, on the FAQ's *"There are mainly three different
Milestones"*. `09-redesign.md` and the v3 specification §1.4 said seven. Both
are wrong; the answer is four.

`?doc=NHPR` is headed **"What is Milestone M4?"** and states:

> Integration of NHPR functionality in the healthcare application/software is
> milestone M4.

| | milestone | source | prerequisite | gateway roles |
| - | --------- | ------ | ------------ | ------------- |
| M1 | ABHA creation, capture and verification | FAQ, `?doc=Milestone_one` | — | `healthId`, `HidAbhaSearch` |
| M2 | HIP — link records to ABHA, consented sharing | FAQ, `?doc=MileStone_two` | none stated | `hip`, `HIP_PAYER` |
| M3 | HIU — consented access to records | FAQ, `?doc=Milestone_three` | none stated | `hiu`, `HIU_PAYER` |
| M4 | NHPR — native health professional and facility registration | `?doc=NHPR` | **M1, M2 and M3** | `hp_id`, `DIGI_DOCTOR`, `hfr`, `bridge` |

**The role map is sourced** (from NHA, 2026-09-05), and it settles what was the
last open question. Two things follow.

M4's four supersede the `?doc=NHPR` page's *"HPID role, HFR role"* rather than
contradicting it: `hp_id` and `hfr` are those two, and the page names what an
integrator must have assigned to start, not the full Keycloak set.

And **legacy's map was right all along** — every one of the ten matches, as
does the v3 specification's §1.4 role column, which had been carrying the same
values with no source behind them. All ten names already exist in
`FAKE_KEYCLOAK_REALM_ROLES` (`config/settings/base.py`), so nothing needs
adding to the fake realm.

**A milestone ordering is stated, once.** `12` §7 says *"There is no milestone
DAG — anywhere."* That is wrong for M4:

> After an entity successfully completed integration of ABDM milestones, M1, M2,
> and M3, integration for M4 can be initiated.

Nothing states M2→M1 or M3→M1, and by the standing rule those stay unenforced
(§8 Q3).

**What is still not a milestone.** PHR, health locker and NHCX. The Test Cases
page numbers Milestones 1–4 as rows 1–4 and lists *"PHR and Locker V3 Test
Cases"* as row 5, outside the numbering. NHCX has its own page describing a
separate programme run with IRDAI. So `12`'s reclassification of PHR and health
locker as `ABDM_ROLES` survives; only M4 was misfiled.

Consequence for the v3 model: with all four milestones owing gateway roles, the
`none_owed` case never arises, and `MilestoneGrant.role_state` collapses to
`12`'s `roles_attached` / `roles_attached_at`. §M-5 was an artifact of treating
PHR and the locker as milestones.

## 3. The exit process, as NHA documents it

`?doc=SandboxExit` is the best source we have on graduation, and it is more
specific than anything in `09` or `10`. Four steps:

| step | what | detail worth keeping |
| ---- | ---- | -------------------- |
| 1a | **Functional testing** | one of **9 named NHA-empanelled agencies**, chargeable. *"should not exceed beyond 7 working days from the date of onboarding"* |
| 1b | **Internal demo by NHA** | FT reports go to NHA first. *"No FT report will be accepted if the report is not in the approved format."* On approval an internal demo is scheduled |
| 2 | **WASA** | STQC **or** CERT-In empanelled. The artefact is a **"Safe-to-Host" certificate** — WASA and Safe-to-Host are the same thing |
| 3 | **HTC approval** (Health Tech Committee) | exit form + artifacts, then *"demonstration of implemented milestones to HTC will be scheduled"* |
| 4 | **Production access** | *"Client-id and Secret for PRODUCTION environment will be shared separately on your registered email address"* |

Four findings that change the plan:

**F1 — there are two demos, not one.** An internal NHA demo *before* the exit
form (step 1b) and a demo to HTC *after* the form is reviewed (step 3). `12`'s
D2 gate treats "NHA demo recorded" as a single submission precondition. Only the
internal demo is a precondition. The HTC demo is a review step and belongs in
the review workflow, not in `SubmitApplication.extra_availability`.

**F2 — the exit artifacts are exactly four**, named in the doc: FT certificate &
reports, WASA certificate, Undertaking, GSTIN certificate. This confirms the v3
specification's B9 block and the four items of its `Verification` table. See R2.

**F3 — the hard copy is real.** *"hard copy of duly signed 'Undertaking' form
must be sent via courier/speed post to NHA office."* So a received-date has to
be recordable by a reviewer; it cannot come from the applicant.

**F4 — M1 must be on V3 APIs.** *"no implementation is accepted for Exit process
if the milestone M1 is done using V1/2 APIs."* The V3 Documentation page gives
the migration deadline as 31-Jan-2025. This sources the v3 model's
`demonstrated_on_current_apis` field, which was previously a guess.

**M4 runs a different evidence track.** Not the empanelled agencies: functional
testing is by NHA's own NHPR team, plus *"Share video recording of the
implemented workflow with NHA"* and *"Security audit report along with VAPT
report"*. So the evidence form is not uniform across milestones — an M4
graduation asks for different uploads than an M1–M3 one.

**One deliberate departure.** NHA emails the production client-id and secret.
The v3 specification §4.2c forbids any message carrying a credential, and v3
shows the secret once in the portal instead. That is an improvement we are
choosing, not a requirement we inherited, and it should be recorded as a change
to NHA's process rather than smuggled in as a port.

## 4. Reconciliation decisions

Each maps a v3-model table onto something that already exists.

| # | v3 model asked for | resolution | why |
| - | ------------------ | ---------- | --- |
| R1 | `Opinion` — a reviewer's advisory recommend/object/query, stamped with the version judged | **drop.** An internal `ApplicationQueryMessage` (`is_internal=True`, `experiences/models.py`) is the opinion | the table adds a dropdown, not a schema. The thread already carries author, body, timestamp and internal visibility |
| R2 | `Verification` — a per-artefact reviewer stamp: who checked it, when, against which version, plus agency, expiry and hard-copy-received date | **already built.** `VerifySecurityEvidence` (`abdm/definition.py:138`) is a reviewer-only `ApplicationFormAction` attached to `SecurityCompliance`. Replicate it for the other three artifacts | it stamps `evidence_verified_at` / `_by` / `verified_revision` into the submission's metadata, and `extra_availability` re-opens the action when the revision moves — so **staleness is already derived from a revision comparison**, exactly §2.2a. An action also takes `cleaned_data`, so the hard-copy date F3 needs is collectable |
| R3 | `BlockAnswer` + `BlockConfirmation` — the four organisation-level blocks stored once, versioned, with each form recording the version it confirmed | **drop both.** The fields are already going onto `Organisation` (`12` §6); forms prefill from there and write back on amendment | the divergence problem is real, the two-table fix is not the cheapest. "What did they claim at submission time" answers itself: cleaned form data lands in `ApplicationFormSubmission.data` as a snapshot, and those rows are immutable |
| R4 | `MilestoneDeclaration` — a table with per-milestone start and end dates | **drop the table, add a form.** A new `MilestoneDeclaration` form definition owning `milestones` and the dates — see §4.1 | the v3 *specification* (B6) asks for these as form fields, and B6 is a block distinct from B4. The data model artifact promoted them to a table; that promotion is the overengineering. Confirmed by grep: no existing ABDM form carries a per-milestone date |
| R5 | `Correction` — NHA editing five permitted fields with a required reason | **drop.** `ApplicationEvent(action_key="correct_field", payload={field, from, to, reason})` | `ApplicationEvent.save()` already raises on re-save. The five-field restriction is a permission, not a table |
| R6 | `CredentialEvent` — that a secret was revealed or rotated, by whom, when | **drop.** An `ApplicationEvent` on the sandbox application | real and worth recording — it answers "who rotated it and when" — but it is an audit line, not an entity |
| R7 | `ExportRecord` — that a console list was exported, by whom, under which filter | **defer.** Nothing to record | grep found no export feature in the console. Revisit when one is built; it is a legitimate data-protection control over bulk PII |
| R8 | `VerificationCode` — email/mobile OTP, ten minutes, ≤5 sends, ≤5 attempts | **keep `sandbox/otp/` as it is.** 129 lines, cache-backed, already sending through the `NotificationGateway` port on `NotificationChannel.SMS` | **mobile only.** allauth already owns email (`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`), so a second record of the same fact would give two answers to one question. The OTP is not state on `User`: the SMS gateway is an external service and it already has a port |
| R9 | `Decision` — eleven typed columns | **`ApplicationInstance.outcome` JSON**, per `12` D1 | accepted. The typing loss is real and priced in |

Already satisfied by the engine, no decision needed: `FormVersion` →
`ApplicationFormSubmission` (which is richer — `submission_number`, `revision`,
partial-unique `is_current`, and a `valid_until` that is exactly the WASA
expiry F2 needs); `Document` → `ApplicationAttachment`; `Thread` /
`ThreadMessage` → `ApplicationQueryThread` / `Message`, whose `QueryStatus`
choices are literally v3's *awaiting applicant | NHA | resolved*;
`HistoryEntry` → `ApplicationEvent`; `StaffRole` → `12` E2/E3.

One genuine gap the engine does not cover: **`ApplicationEvent` has no
`is_internal`**, so v3 §4.7's "hidden from the applicant" has nowhere to live.
**Add the flag** (decided 2026-09-05), matching `ApplicationQueryMessage`, which
already has one. A projection filtered by `kind` was the alternative and is
worse: it makes visibility a property of the event's type rather than of the
event, so one internal note of an otherwise public kind cannot be hidden.

### 4.1 A `MilestoneDeclaration` form, split out of `IntegrationScope`

R4 first put the dates on `IntegrationScopeForm` because that is where
`milestones` lives today. On reading the form, a separate definition is better,
and for four reasons rather than tidiness.

**`IntegrationScopeForm` is already two forms.** Its own description reads
*"HIP, HIU, health-locker roles and completed sandbox milestones"* — roles and
milestones — and it also carries `sandbox_client_id`, `hfr_facility_ids`,
`health_information_types`, `integration_approach` and `connector_name`. Adding
eight conditional date fields to a seven-field form makes a fifteen-field form
where more than half the fields are conditional on checkboxes inside it.

**It matches a block boundary the specification already drew.** B4 (integration
scope) is asked once at registration; B6 (milestone declaration) is graduation
only. R3 puts B4's answers on `Organisation`, which leaves `IntegrationScope`
as the B4 confirmation — and milestones were never B4.

**It is what makes D9 cheap.** M4's different evidence set becomes a form
gated by `is_applicable`, which is the pattern `HealthLockerOperations` already
uses against `IntegrationScope`:

```python
class NhprEvidence(ApplicationFormDefinition):
    key = "nhpr_evidence"
    dependencies = (MilestoneDeclaration.key,)

    @classmethod
    def is_applicable(cls, context):
        declared = context.form_data(MilestoneDeclaration.key).get("milestones", [])
        return "m4" in declared
```

**`12` decision 2 does not forbid it.** That decision rejected *per-milestone*
form definitions — one form each — and its stated justification was that they
"were only ever justified by per-form review, which D1 removes". One generic
form owning one block is not that, and the reasoning does not reach it.

The shape:

```python
class MilestoneDeclaration(ApplicationFormDefinition):
    key = "milestone_declaration"
    name = _("Milestone declaration")
    form_class = MilestoneDeclarationForm
    dependencies = (IntegrationScope.key,)
    allow_updates = True

    @classmethod
    def metadata_updates(cls, cleaned_data, context):
        return {"milestones": cleaned_data["milestones"]}
```

Three consequences to handle:

- **The date fields are built in `__init__`**, looping `MILESTONES`, rather
  than eight static declarations — so M5 costs nothing. `12` D4 already
  narrows `ApprovalForm.approved_milestones` the same way, so dynamic field
  construction is an accepted idiom here.
- **`IntegrationScope` sheds `milestones`** and the `hip → m2` / `hiu → m3`
  rules move with it. They run in `MilestoneDeclarationForm.clean()`, reading
  roles through `experience_context`, which `ExperienceForm.__init__` already
  accepts. Ordering the dependency `IntegrationScope → MilestoneDeclaration` is
  what makes this direction the possible one: roles are recorded first, then
  milestones are validated against them.
- **D7's `m4 → m1+m2+m3`** lands in the same `clean()`, satisfied by a grant
  already held or a milestone declared on the same form.

## 5. Net model delta

Unchanged from `12` §4. Recorded here only so this document can be read alone.

```
NEW           MilestoneGrant · NotificationLog
KEPT          ProvisionedResource (sandbox/integrations, §9.3)
ENGINE        ApplicationEvent gains is_internal — §4
```

`MilestoneGrant` keeps `12`'s shape — `roles_attached`, `roles_attached_at` —
with role-attachment failures going to `ApplicationEvent`. §2 is why the
three-state `role_state` is not needed.

`ProvisionedResource` is **not** written from scratch — it exists, and §9.3
records where the shape here was wrong.

`NotificationLog` keeps `12`'s `template_key`. The v3 model's `body_as_sent` and
`resent_from` were there to make "a resend reuses the original wording"
enforceable; that is a service-layer guarantee, and a test can hold it.

## 6. Domain fixes, revised against §2 and §3

Supersedes `12` §5 where they differ.

| # | change | status |
| - | ------ | ------ |
| D1 | health information types 6 → 8 | unchanged |
| D2 | exit gate — FT evidence · unexpired `wasa` `security_certification` · **internal** NHA demo recorded | **narrowed by F1.** The HTC demo is a review step, not a submission gate |
| D3 | drop `wasa_certificate_number` from `SecurityComplianceForm` | unchanged |
| D4 | decision-time ceiling on `ApprovalForm.approved_milestones` | unchanged |
| D5 | `ABDM_ROLES` gains `hrp` | unchanged |
| D6 | ~~`MILESTONES` stays `[m1, m2, m3]`~~ → **`[m1, m2, m3, m4]`** | **corrected by §2** |
| D7 | *new* — enforce `m4 → m1 + m2 + m3` in `clean()`, satisfied by a milestone already held in `MilestoneGrant` or declared on the same application. **The only prerequisite there is**: M2 and M3 have none | sourced by §2; the M2/M3 half decided 2026-09-05 |
| D8 | *new* — a `MilestoneDeclaration` form owning `milestones` and per-milestone start/end dates, split out of `IntegrationScope` | R4, §4.1 |
| D9 | *new* — an `NhprEvidence` form, `is_applicable` when M4 is declared: video recording of the workflow, security audit **and** VAPT report; functional testing by NHA's NHPR team rather than an empanelled agency | §3, §4.1 |
| D10 | *new* — government applicants declaring M1 must additionally cover Aadhaar Biometrics and offline Aadhaar Demographics | §7 |
| D11 | *new* — record `demonstrated_on_current_apis` on the decision; an M1 graduation on V1/V2 APIs is not acceptable | F4 |

The existing `hip → m2` and `hiu → m3` rules in `abdm/forms.py` are sourced by
the FAQ's own milestone descriptions and stay exactly as they are.

## 7. Sourced facts added

Recorded because each replaces a guess.

**The M1 government matrix** (`?doc=Milestone_one`) answers what the v3
specification left open as Q2 — whether NHA's additional M1 requirements for
government applicants are enforced or merely displayed. They are a real
distinction:

| M1 capability | private | government |
| ------------- | ------- | ---------- |
| ABHA via Aadhaar OTP | mandatory | mandatory |
| ABHA via Aadhaar biometrics | optional | **mandatory** |
| ABHA via offline Aadhaar demographics | n/a | **mandatory** |
| ABHA via driving licence | optional | optional |
| Create ABHA address · download card · scan facility QR · verify by OTP · new vs returning | mandatory | mandatory |

**Registration collects** entity name, email, password, website and *intent to
integrate*. Email is the login identity. Confirms B1/B3 and confirms M-6 —
intent is stated at registration and grants nothing.

**Scan and Pay** (`?doc=scan-and-pay-2`) carries a dependency worth knowing
about even though it is not a milestone: an HMIS must be *"at least M3
integrated"*, a PHR app *"at least M2 integrated"*. A use-case gate, not a
milestone gate.

**Reference-only tabs**, no model impact: Swagger (ABHA / HIP / HIU / PHR / ABHA
Address / HIE-CM), Postman Collection, V3 Documentation (12 downloads), HPR,
UHI, NHCX Integrators, Building a PHR App, Use Cases.

## 8. Open questions

Carried from `12` §9. **All five are now closed**; kept with their
resolutions so the reasoning is not lost.

1. ~~**Product.**~~ **Closed (2026-09-05): abandoned as a concept.** Not
   deferred — removed. One organisation is one product, `MilestoneGrant` stays
   organisation-scoped, and `integrations/` stops reaching through
   `application.product` (`14` §5.1). Reintroduce only if a vendor arrives with
   two ABDM-integrating products, and treat that as new work rather than as a
   restoration.
2. ~~**M4.**~~ **Closed by §2.** M4 is NHPR, it is a milestone, and it requires
   M1+M2+M3.
3. ~~**Milestone DAG, the rest of it.**~~ **Closed by decision (2026-09-05):
   M2 and M3 have no prerequisite.** Neither NHA document states one, and the
   standing rule is that what the documents do not say, we do not enforce. M4's
   `m1 + m2 + m3` is the only prerequisite, and it is sourced (D7).
4. ~~**the role map for M1–M3.**~~ **Closed (2026-09-05)** — supplied by NHA
   and recorded in §2. `MilestoneGrant.roles_attached` can now be written.
5. ~~**does `ApplicationEvent` gain `is_internal`**~~ **Closed: yes** (see §4).

## 9. The external integrations stay

`sandbox/integrations/` is the usable part. Keycloak, WSO2, HIE-CM and the
notification gateway sit behind `ports.py` protocols with a
`settings.INTEGRATION_PORTS` registry and 400 lines of fakes; none of that is
redesigned and none of it moves.

What changes is only its wiring, because it currently talks to two things that
are dropped — `sandbox/workflow/` and `sandbox/applications/`:

| today | becomes |
| ----- | ------- |
| `hooks.py` — `register_hook("provisioning_chain", …)` | an entry in the approve action's `ActionResult.effects` — E1 |
| `services.py`, `tasks.py` — `transition(action="FAIL_PROVISIONING")` | a status write plus an `ApplicationEvent` |
| `Application` / `ApplicationState` | `ApplicationInstance` / registry status keys |

Three more notes, and then this section is done:

- **Use the existing `ProvisionedResource`.** §5 and the ER drawing describe a
  shape the code contradicts: it is scoped to the application alone (no
  organisation FK), its states are `ACTIVE / DISABLED / FAILED / ORPHANED`, and
  `NOTIFICATION` is deliberately not a system because it is sent through, not
  provisioned into.
- **The counting rule is already there.** `complete_provisioning` reads the
  ACTIVE rows and parks the application naming what is missing. Do not rebuild
  it.
- **Deprovisioning already exists** — a reverse chain on rejection and
  withdrawal. `12`'s E4 adds a withdraw action with nothing behind it, so E4
  should reach this chain rather than invent one.

## 10. Build order

`12` §10 stands. Three amendments:

- **Step 3 (domain fixes)** grows by D7–D11. It is also where the
  `MilestoneDeclaration` and `NhprEvidence` forms land (§4.1), and where
  `VerifySecurityEvidence` is replicated for the other three artifacts (R2).
- **Step 2 (models)** shrinks: R1, R3, R4, R5, R6, R7 remove every table the v3
  model would have added beyond `12` §4.
- **A new step 0**: put Q4 — the M1–M3 role map — to NHA, before the domain
  fixes need it.
- **Step 4 (`integrations/`)** is smaller than `12` implies: the adapters stay
  as they are, and only the wiring in §9 changes.
