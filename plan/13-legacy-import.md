# Importing legacy into the rebuilt portal

Everything about moving legacy's data into the design `12-abdm-portal-rebuild.md`
describes. That document defines the shape; this one defines how existing
records reach it. Where the two disagree, 12 wins and this file is wrong.

Figures from the legacy database are deliberately not reproduced here. Where a
conclusion rests on one it names the table it came from; re-run the query
against a local restore if it needs confirming.

---

## 1. Reshape, do not copy

Legacy is not imported in its own shape and then adapted. The importer builds
our objects — an `Organisation`, an `ApplicationInstance`, an
`ApplicationFormSubmission` per form, the milestone grants, and a
`ProvisionedResource` cross-referencing the client that already exists. The
legacy row is *input*, and nothing in the result is described by its identifier.

## 2. Where each thing lives

| table | holds |
| ----- | ----- |
| `sd_login` | the integrator and the application, fused into one row |
| `sd_status` | the decision, and the Keycloak client id it issued |
| `sd_exit` | the exit application |
| `sd_exit_docs` | the exit evidence, typed by `sd_doc_type` |
| `active_integrator` | the public listing that `Organisation.listing_hidden` answers |

The client ids in `sd_status` name clients that live in **NHA's Keycloak realm**,
not in any database of ours. The importer cross-references them; it does not
create them, and starting without them would leave every one of those clients
unowned — which is exactly what P4's reconciliation sweep flags as `ORPHANED`.

**`sd_exit`'s inline document columns are stale.** `wasa_file`, `host_file`,
`function_testing_file` and `policy_file` are BYTEA columns superseded by
`sd_exit_docs`. Read the inline columns and the evidence looks almost entirely
absent; read the table and most decided exits have it. `policy_file` was never
used at all. Do not write the importer against the columns.

**Other application types have their own tables.** 12 §1.2 brings two of them
into the design as application types of their own — `sd_exit_live` becomes
`abdm_go_live` and `nhcx_exit` becomes `abdm_nhcx_exit` — so they are in scope
for the import, in that order and after the milestone exits they follow.
`sd_hiu` and `sd_uhi` remain out of scope.

## 3. Splitting the fused row

`sd_login` is the integrator *and* the application, so splitting it gives one
`Organisation` **and** one `ApplicationInstance`. That makes
`sd_id → ApplicationInstance` 1:1 and `sd_id → Organisation` many:1.

So the legacy key lives in **a mapping table the importer owns** — `sd_id` ·
organisation · application · imported_at — not on a core model. It records both
halves of the split, gives a re-runnable import somewhere to be idempotent
from, and is droppable after cutover. `Organisation` gains no column for it
(12 §8.3).

### 3.1 Repeat applicants

A minority of applicant emails hold several `sd_login` rows. Every one of those
rows becomes its own `ApplicationInstance` regardless — each has its own client
id — so the only question is how many organisations they produce. Three cases,
by how many distinct organisation names the email carries:

| the email's rows carry | becomes |
| ---------------------- | ------- |
| no organisation name at all | one `Organisation` for the person (12 §4.5), N applications |
| exactly one organisation name | one `Organisation`, N applications |
| **more than one** | **one `Organisation` per distinct name** |

The first two are the large majority. The third is a small tail — under a
percent of distinct emails, at worst three names on one address.

**One organisation per distinct name, not per email.** An address carrying
several company names is far more likely a consultant or systems integrator
applying for several clients than one company that renamed. If it *is* a
rename, two organisations is a recoverable error — merge them — where one
organisation is not: that silently fuses two vendors and their credentials. The
email becomes a `Membership` on each, which the model already supports.

Two rules that follow:

- **Match on a normalised name**, casing and punctuation stripped. On raw
  values the count is higher and wrong, for the same reason `entity_type` needs
  mapping rather than copying (§4).
- **Emit the third case as a review list.** It is small enough for a person to
  read, and NHA will recognise the agencies on sight.

## 4. Field mappings

**`entity_type` → `NatureOfEntity`.** Legacy stored it as free text, so its rows
carry casing and whitespace variants of the same answer alongside free-form
prose. The importer maps onto the enum; it cannot copy, and a `CHECK`
constraint means a straight copy fails loudly rather than quietly.

**`application_type = '2'` → `nature_of_entity = INDIVIDUAL`.** Legacy carried
individuality in that separate code and left `entity_type` blank for those
rows, so the fact cannot be read off `entity_type` at all. 12 §4.5 has the
design; this is the mapping.

**`self_declaration` → the milestone declaration.** Legacy's own version of the
same form, and the closest structural match in the dump: `complete_mil`,
`will_complete_mil`, `working_on`, and start/end date pairs per milestone. Two
differences to settle rather than discover:

- It carries date pairs for `phr`, `health_locker` and `nhcx` as well. 12 §3.1
  makes those roles and a separate programme, not milestones, so those dates
  have no field to land in.
- It records *planned* milestones (`will_complete_mil`, `working_on`) where
  ours records only what is complete.

**`sd_exit.integration_detail` → the milestone declaration.** A free-text,
comma-separated list carrying `m1`…`m4` mixed in with `phr`, `health locker`
and `nhcx`. Only the first four are milestones (12 §3.1): PHR and health locker
map onto `ABDM_ROLES` and NHCX is a separate programme, so the importer splits
this one field three ways rather than copying it. `milestone_dif` is a
yes/no answer to a different question and is not the milestone list.

**M4 carries no evidence to import.** Legacy has no NHPR testing reference,
VAPT or recording anywhere, so a migrated M4 application arrives with its
`nhpr_evidence` form empty — the same open question as §6's first item.

**Names sent onward are sanitised** by `integrations.tasks._external_name`,
reproducing legacy's `[^a-zA-Z0-9]` → space. One deviation: legacy replaced
each character singly and trimmed only the ends, leaving double spaces inside;
runs collapse here. Safe, because migrated integrators are not re-provisioned —
this only names clients created after cutover.

**`entity` went out as the literal `"NA"`** for individuals, a placeholder for a
null. Ours is `nature_of_entity = INDIVIDUAL`, which is better information, but
it changes what any downstream consumer of the bridge table's `entity` column
receives.

### 4.1 Reading the legacy UI

Faster than the database for "did the portal ever ask this?", and it answers a
different question — what the form offered, rather than what got stored. The
legacy portal is a single unlazy React bundle, public at
`/sandbox/v3/static/js/main.*.js`; fetch it and count occurrences.

Probe for terms the exit form certainly has before trusting an absence:
`selfDeclaration`, `Milestone`, `WASA`, `Undertaking`, `Exit Form` all appear
in the hundreds. Against that baseline, a zero means the portal genuinely never
asked. This settled 12 §6's D9 and D10 in one pass, and corrected D5.

## 5. Legacy roles

Each of legacy's eight `mst_role` rows, and what it becomes under 12 §5.

| legacy role | maps to |
| ----------- | ------- |
| Super Admin | every permission, plus Django superuser |
| HTC | `decision_maker` — the same HTC as 12 §3.2 step 3 |
| Role_Admin_view | `reviewer` — see below |
| User | integrators; no review role at all |
| User_view | a `user_view` role holding **no permissions** |
| UHI Application | **blocked** — 12 §5.5 |
| nhcx | **blocked** — 12 §5.5 |
| UHI | drop, unassigned |

**`User_view` maps to an empty role, which is now safe.** Its users have no
privilege row, so today they get a 500. `permissions = []` reproduces what they
effectively have, without the crash.

**`Role_Admin_view` has never decided anything.** `sd_status` carries five actor
columns — `admin_id` and `htc1_id`…`htc4_id`, foreign keys to `sd_login.sd_id`.
Resolving every recorded decision to its actor's role yields exactly two, HTC
and Super Admin; `Role_Admin_view` appears in none of them. Every screening
decision was made from the Super Admin account and every committee decision
from an HTC account. So although the role *can* decide — it holds `All
Application List`, and the action verb is decorative (12 §5.2) — nobody has
ever used it to. Mapping it to `reviewer` withdraws a capability that has never
once been exercised, which is as close to safe as a migration gets.

Worth telling NHA in its own right: a handful of people hold a role with rights
the evidence says they have never used.

**A correction to an earlier draft.** An earlier version of this analysis said
`sd_status` had "no actor columns at all" and that the question could not be
settled empirically. Both were wrong, and from the same mistake: the columns
were searched for by name pattern — `%by%`, `%user%` — which `admin_id` does
not match, and absence from a filtered query was reported as absence from the
table. `sd_exit` and `nhcx_exit` genuinely have none, so the accountability gap
`ApplicationEvent` and `decided_by` close is real for the exit and NHCX
records — just not for `sd_status`.

## 6. Open

1. **Evidence that never reached the system.** A minority of decided exits have
   no document at all, matching 12 §3.2's hard-copy received date — the
   assessment arrived outside it. A synthesized `security_certification`
   submission is therefore complete for most and empty for a tail of
   integrators who are approved regardless. Marking them complete asserts
   evidence we do not hold; marking them incomplete shows approved integrators
   as unfinished. A third state — migrated without evidence — is probably the
   honest answer, and it is a form-state decision rather than a mapping one.

2. **Same realm or new?** If the rebuilt portal points at legacy's Keycloak
   realm, the import is the cross-reference described in §2. If it points at a
   new one, every approved integrator needs re-provisioning and new
   credentials — different work entirely, and it changes what the mapping table
   is for. Nothing here is safe to build until this is answered.

3. **`Super Admin` and `user_view` are not seeded.** The seed migration creates
   three roles. Either add them there or leave them to this importer.

---

## 7. Importing into four application types

12 §1.2 split one application type into four. Everything below is what that
costs the importer, and it is mostly good news: legacy's own tables already
have this shape, and the one-application design was the thing that did not.

| legacy table | becomes | key |
| ------------ | ------- | --- |
| `sd_login` + `sd_status` | one `abdm_sandbox_access` | `sd_id` |
| `sd_exit` | one `abdm_milestone_exit` **each** | `sd_exit.id`, pointing at its `sd_id`'s sandbox access |
| `nhcx_exit` | one `abdm_nhcx_exit` each | same |
| `sd_exit_live` | one `abdm_go_live` each | same |

`sd_exit.sd_id` is already the pointer 12 §1.2 asks a milestone exit to carry,
so "which sandbox access is this for" needs no inference — it is a foreign key
that has always been there. The mapping table §3 describes gains a row per exit
alongside its row per registration.

### 7.1 The importer must bypass `can_start`

Nearly every exit follows an approved registration, which is what makes the rule
worth enforcing for new applications. But not every one: a small number of
integrators filed exits while their registration stood rejected, and a handful
have no client id at all.

So `can_start` is checked in `create_application` and **nowhere else**. If it
were a model-level invariant or a database constraint, those rows would fail to
import and the import would quietly be short. Legacy's history is not required
to satisfy rules written after it.

### 7.2 `product` is null for most imported rows

Most `sd_login` rows carry no product name, and the distinct product count
across the whole dump is a small fraction of the row count. The importer creates
a `Product` only where there is a name to create one from, matching on the
normalised name within the organisation so that repeat registrations of the same
product converge on one row rather than one each.

Everything else imports with `product = NULL`. This is why 12 §1.2 makes the
column nullable: the alternative is a placeholder product for the majority of
the dump, carrying no information and permanently indistinguishable from a real
one.

### 7.3 Exits are concurrent, so nothing may serialise them

Of the integrators who filed more than one exit, roughly two in three had two
open at once. An importer that assumed one-at-a-time — or a model that enforced
it — would reject real history. The pre-port `Application` model's
`(product, workflow_key)` in-flight uniqueness constraint is the specific thing
not to revive.

### 7.4 What one exit's milestones become

`sd_exit.integration_detail` is the milestone list (§4). Each `m1`…`m4` it names
becomes a `MilestoneGrant` on the organisation where the exit was approved; `phr`
and `health locker` map onto `ABDM_ROLES` and `nhcx` is dropped from this field,
because that integrator's NHCX filing is its own row in `nhcx_exit` and imports
as its own application.

Bundling means one imported exit routinely writes several grants. The unique
constraint on `(organisation, milestone)` does the deduplication where two
approved exits claim the same milestone — first one wins, which is the right
answer since the grant is the durable fact and not the filing.
