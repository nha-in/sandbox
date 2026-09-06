# 11 — Workflow rewrite: the form is the thing that travels

Status: agreed design, ready to build (2026-09-02). Supersedes the
engine/definitions design of `09-redesign.md` §2–§5 where they conflict.
DB compatibility with the current tables is a non-goal — rewrite, not
migration.

## 1. Why

The ported design declared a per-workflow state machine (an 8-field
`TransitionSpec` per edge). Killed because: workflows are 99% identical
(submit → review → approve / reject / send back → resubmit); transitions
mixed every concern; state lived in four bookkeeping surfaces that could
disagree (two round counters did). Resolution: **the review cycle is the
normal behavior of a form submission; status is where one passage sits
inside it.** There is no application-level state machine.

## 2. The model

Four tables. (Sketches show lifecycle columns only; `reference`,
`applicant`, timestamps and soft-delete carry over unchanged.)

```
Application                      # a container, nothing more
    product, workflow_key
    withdrawn_at                 # the only lifecycle fact it owns
    # unique (product, workflow_key) WHERE withdrawn_at IS NULL:
    # one live enrollment per programme — a create-time check would race

FormSubmission                   # one row = ONE passage through the cycle
    application, form_key
    cycle                        # 1, 2, 3… per (application, form_key):
                                 # counts reviewer passes, not keystrokes
                                 # unique (application, form_key, cycle)
    data, schema_version         # mutable while DRAFT; frozen at submit
    status                       # DRAFT | SUBMITTED | APPROVED | REJECTED | SENT_BACK
    submitted_by, submitted_at   # set once, when the row freezes: submit() or record()
    documents (M2M → Document)   # which artifacts THIS cycle carries
    # DB teeth: DELETE revoked; trigger — data/documents mutable only while
    # DRAFT, status only along DRAFT→SUBMITTED→{APPROVED,REJECTED,SENT_BACK}

Document                         # immutable artifact: uploaded once, never edited
    kind, storage_key, filename, content_type, size, sha256
    uploaded_by, uploaded_at

Review                           # recommendation and decision are one row type
    submission (FK), author, created_at
    verdict                      # APPROVE | REJECT | SEND_BACK
    comment
    binding                      # True when this row IS the decision
    # append-only, no unique constraint: a re-review is a new row; screens
    # read all rows per submission newest-first, history kept for free
```

### The cycle

```python
def current(application, form_key):
    # never submitted_at: NULL while drafting, not monotonic across updates
    return rows(application, form_key).order_by("-cycle").first()

def new_cycle(prev, data=None):
    # lazy: called on the first CHANGE after send-back/reject, or by an
    # unchanged resubmit — never eagerly, so a review always sits on
    # exactly the row it judged and no empty rows exist
    row = FormSubmission.create(
        application=prev.application, form_key=prev.form_key,
        cycle=prev.cycle + 1, data=data or prev.data, status=DRAFT,
    )
    row.documents.set(prev.documents.all())   # POINTS at the same artifacts
    return row

def replace_document(draft, old_document, upload):
    # by id, never by kind: one cycle can carry several documents of one
    # kind (a WASA certificate per platform: iOS / Android / web)
    require(draft.status == DRAFT)            # frozen after submit
    draft.documents.remove(old_document)
    draft.documents.add(Document.create(upload))
    # the old Document row still exists and still hangs on every earlier
    # cycle — walk the cycles and both artifacts are reachable, full history
```

- **Draft → submitted is the same row.** After submit, `status` is the only
  column that ever changes on a row.
- **Artifacts are immutable; cycles point at them.** An unchanged
  certificate is one `Document` linked from every cycle that carried it; a
  replacement is a second row.
- **History is not a mechanism** — it is the decided rows sitting there.
- `REJECTED` and `SENT_BACK` are mechanically identical; the distinction is
  vocabulary for applicants and records — do not invent a mechanical one.
- **Repeatable reviewed forms (exit claim) reuse the same chain**: after an
  `APPROVED` cycle, the next change starts a new cycle that re-enters
  review. An “exit” is a derived grouping — a maximal cycle run ending
  `APPROVED` — nothing gates on the boundary (grants are per-APPROVED-row
  unions), only display segments it.
- Decision authorship has one home: the binding `Review` row. Recorded rows
  (§3) have no `Review` rows; their authorship is `submitted_by`.

### Status above the form is always derived

- "Under review" = _submitted + has recommendations + undecided_; not a
  status. The enum holds five facts, no process-theatre states.
- Application-level status is a display summary. Nothing gates on it.
- `WITHDRAWN` is `Application.withdrawn_at`, not a form status.
  **Withdrawal stops verbs, not reads**: rows stay frozen facts, reusable
  by other programmes' predicates (§8.6); every verb refuses on a withdrawn
  application, queues exclude its submissions.
- Provisioned-ness derives from credentials (§7); compliance and DHIS
  eligibility stay computations over decisions.

### Derived facts have one home: `workflow/derived.py`

One spelling per fact: a queryset annotation for list screens plus a
pure-Python twin where a detail screen already holds the rows, one test
pinning the two (same discipline as §4's authz pin). Sized honestly: the
queue is `status=SUBMITTED`, dashboards are aggregates, the applications
list is one CASE annotation, "exit N" / application summaries are pure
functions over prefetched rows. Promote to a cached column only under
measurement, maintained inside the verbs, name unchanged. Never
pre-materialize.

### What the model makes unrepresentable

| former mechanism                    | why it cannot happen now                                                                                                                               |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| illegal transitions                 | you cannot decide an unsubmitted row or submit a decided one — status checks, not a graph                                                              |
| two passages of one form in flight  | partial unique: one row per `(application, form_key)` with `status IN (DRAFT, SUBMITTED)` — this is also what makes a second undecided exit impossible |
| round-counter drift                 | `cycle` is the row itself; reviews FK the exact row they judged                                                                                        |
| edited history                      | rows are frozen at submit — trigger-enforced (§2), drafts are the only mutable rows                                                                    |
| transition log diverging from truth | there is no separate log — the rows are the history (audit events remain)                                                                              |

## 3. The verbs — the entire engine

Five functions, the only write paths; each user act is its own endpoint
(draft / submit / record / verdict / withdraw) — the engine never infers
the act from form flags. Each emits audit; effects are Celery task
enqueues strictly `on_commit`, so the broker owns retries. Locking:
**every verb first takes `select_for_update` on the application row**;
`current()`, cycle allocation and `withdrawn_at` are read only behind it.
One lock closes them all: two saves minting the same cycle (the
`(application, form_key, cycle)` unique backstops), a decision landing
after a withdrawal, two binding reviews, the registration-update-vs-exit
ceiling race (§5 — same row). Cross-programme reads of frozen `APPROVED`
rows need no lock. Guards and effects are **direct callables** — a missing
one is an import error at boot, not a silent no-op.

### `save(application, form_key, data, user)` — drafting, reviewed forms only

Every arm answers one question: where is the current passage in the cycle.
Writes that skip review live in `record()`, not in flag arms here.

```python
def save(application, form_key, data, user):
    lock(application)
    require(application.withdrawn_at is None)
    require(can(user, application, "submit"))   # drafting is part of submitting
    form = definition(form_key)
    require(form.reviewed)                      # record forms have no drafts

    match status_of(latest := current(application, form_key)):
        case None:                  return create(cycle=1, data, status=DRAFT)
        case DRAFT:                 latest.data = data; latest.save()
        case SUBMITTED:             refuse("frozen under review")
        case SENT_BACK | REJECTED:  return new_cycle(latest, data)   # lazy (§2)
        case APPROVED if form.repeatable:       # exit claim: the NEXT exit —
            return new_cycle(latest, data)      # a DRAFT that re-enters review;
                                                # docs carry (WASA reuse, §8.1)
        case APPROVED:              refuse("nothing to update")
```

### `record(application, form_key, data, user)` — writes that skip review

One act: append a frozen `APPROVED` cycle row — record forms (DHIS claim)
and post-approval updates of an `updatable` form (registration, §8.3).

```python
def record(application, form_key, data, user):
    lock(application)
    require(application.withdrawn_at is None)
    require(can(user, application, "submit"))
    form = definition(form_key)

    if form.reviewed:                           # registration update (§8.3)
        require(form.updatable)
        require(current(application, form_key).status == APPROVED)
        require(no_undecided_exit(application))  # same app, same lock
    row = build(next_cycle(), data, status=APPROVED,     # unsaved candidate:
                submitted_by=user, submitted_at=now())   # checks see NEW data,
    for check in form.checks:                   # not the previous cycle's
        check(row)
    return row.save()                           # frozen on save
```

### `submit(application, form_key, user)`

```python
def submit(application, form_key, user):
    lock(application)
    require(application.withdrawn_at is None)
    require(can(user, application, "submit"))
    form = definition(form_key)
    latest = current(application, form_key)     # the app lock covers it

    if latest.status in (SENT_BACK, REJECTED):
        latest = new_cycle(latest)              # unchanged resubmission, same tx
    require(latest.status == DRAFT)

    for check in form.checks:                   # every business rule, one place
        check(latest)
    latest.submitted_by, latest.submitted_at = user, now()
    latest.status = SUBMITTED                   # data + document links frozen
```

| form                  | `checks` at submit                                                                                                                                                                                                                    |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| registration          | none beyond form validity                                                                                                                                                                                                             |
| milestone declaration | enrollment approved · credentials exist                                                                                                                                                                                               |
| exit claim            | claimed milestones staff-approved (own application; a cross-programme exit reads the sibling enrollment) · WASA `valid_upto` not expired · required documents attached (≥1 per required kind — a cycle may carry several of one kind) |

One exit in flight = the partial unique (one DRAFT/SUBMITTED row per
`(application, form_key)`), not a check. One live enrollment per
(product, workflow) = the `Application` partial unique (§2), not a check —
at create time there is no application row to lock.

### `review(submission, user, verdict, comment="", decide=False, decision_data=None)`

```python
def review(submission, user, verdict, comment="", decide=False, decision_data=None):
    lock(submission.application)          # same lock as withdraw: a decision
    submission.refresh_from_db()          # cannot land past a withdrawal
    require(submission.application.withdrawn_at is None)
    require(submission.status == SUBMITTED)   # racing admins: second sees a decided row
    form = definition(submission.form_key)

    if not decide:                        # intent is the caller's — an approver
        require(can(user, submission, "review"))      # may merely advise
        require(decision_data is None)
        return Review.create(submission, user, verdict, comment, binding=False)

    require(can(user, submission, verdict.lower()))   # approve_<p> / reject_<p> / …
    if verdict == APPROVE and form.decision_form:
        require(decision_data is not None)
        write_decision(submission, decision_data, user)  # same transaction as the move
    else:
        require(decision_data is None)

    row = Review.create(submission, user, verdict, comment, binding=True)
    submission.status = verdict                       # the review IS the decision
    on_commit(form.effects_for(verdict))              # on_approved / on_rejected / on_sent_back
    return row
```

Four-eyes (binding requires another author's prior recommendation) is
deliberately not enforced — team norm, not invariant; a one-line check in
`review()` if that ever changes.

### `withdraw(application, user, comment="")`

```python
def withdraw(application, user, comment=""):
    lock(application)
    require(can(user, application, "withdraw"))
    require(application.withdrawn_at is None)   # allowed even after approval:
    application.withdrawn_at = now()            # leaving the sandbox IS withdrawal
    on_commit(teardown)                         # idempotent: may have provisioned nothing
```

## 4. Authority: permissions are the only concept

One question gates every act, on the submission or its application:

```python
user.has_perm(f"workflow.{verb}_{programme}", obj)
```

- Roles are Django groups, named and composed per deployment; the verbs
  never check a role name or `is_staff` — only the held permission.
  Permission names are minted at migrate time from the vocabulary ×
  registered programmes; a programme may declare extras
  (`retry_provisioning_abdm`).
- Ownership is a source of permissions, not a category: `OwnershipBackend`
  computes `view / submit / withdraw` from org membership — never stored;
  membership ends, permissions end. Answers for both `Application` and
  `FormSubmission`.
- No `ActorKind`, no owner/staff taxonomy anywhere in the engine.
  Delegation later is a grant, not an engine change.
- Console buttons use the same `can()` used for enforcement. List pages
  restate the two permission sources in SQL (role-held `view_<p>` →
  `workflow_key` set; membership → organisation filter); a test pins the
  backend and the queryset scope to each other.

**Reviewer and admin are one endpoint**: `decide` plus the caller's held
permissions determine whether a verdict recommends or decides.
"Reviewer" / "approver" are descriptions of whoever holds `review_<p>` /
`approve_<p>`, not roles this system defines.

## 5. What a programme defines

Everything consequential lives on the **form**; a workflow is a named set of
forms — flows that only offer a subset (say M1 + M3) are new named sets, not
new machinery.

```python
# sandbox/programmes/abdm.py
class Registration(FormDefinition):
    form_class = RegistrationForm
    updatable = True                       # §8.3: post-approval edits via record()
    on_approved = (integrations.start_provisioning,)

class MilestoneM1(FormDefinition):         # generated per milestone, as today
    form_class = MilestoneDeclarationForm
    checks = (enrollment_provisioned,)

class DhisClaim(FormDefinition):
    form_class = DhisClaimForm
    reviewed = False                       # record form: written by record()
    repeatable = True

class ExitClaim(FormDefinition):           # WASA is a section of this form (§9.1)
    form_class = ExitClaimForm
    repeatable = True                      # next exit = next cycle run (§2, §8.6)
    checks = (exit_gate,)
    decision_form = ExitDecision           # written inside binding approve
    on_approved = (grants.grant_exit, notify.exit_approved)
    on_rejected = (notify.exit_rejected,)
    on_sent_back = (notify.exit_sent_back,)

class ABDM(Workflow):                      # workflow = programme; exits are
    forms = (Registration, *MILESTONE_FORMS, DhisClaim, ExitClaim)   # forms in it
```

- `key` derives from the class name, `programme` from the module, labels
  from keys; all overridable. A registry test pins known keys so a rename
  cannot silently mint a new identity.
- Deleted per-workflow: `permissions`, `view_permission`,
  `review_permission`, `transitions`, `initial_state`, `terminal_states`,
  `resting_states`, and the `PERM_*` / `ABDM_PERMISSIONS` blocks.
- Everything that makes ABDM ABDM survives untouched: the milestone DAG, the
  DHIS matrix, the four predicates, the Django forms.

## 6. Milestones are reviewed; the console's unit is the submission

Milestone declarations are ordinary reviewed forms — submitted by the
applicant, decided by staff — so an exit claims only staff-approved
milestones. An approved milestone is a **cross-programme fact** (M1 is NHR
integration whether the claiming exit is ABDM's or HCX's); §8.2's reuse is
only sane if a human approved the row. Consequences: several submissions
per application can await review at once — **the console queue's row is
the FormSubmission, not the Application** — and reviewer workload grows vs
today (NHA informed, not blocking).

## 7. Provisioning is not workflow

The provisioning states and the SYSTEM actor existed only to jam an async
job into the review lifecycle. **The credentials are the fact**: an
application is provisioned iff its `ProvisionedResource` rows exist. What
remains is an attempt log:

```
ProvisioningAttempt: application · started_at · finished_at · error
    # one open attempt per application: partial unique WHERE finished_at IS NULL
    # tasks carry attempt_id; abort if attempt closed or application withdrawn
```

- Kicked by `Registration.on_approved`; retry is its own verb gated by
  `retry_provisioning_<p>`; teardown on withdraw (idempotent).
- Console derives the display: credentials exist → "Provisioned"; latest
  attempt errored, no credentials → "Provisioning failed [Retry]".
- Same discipline as the verbs — single write path, atomic, audited — and
  zero contact with `workflow/`.

## 8. Decisions log

1. **WASA travels with the exit form** — a section of it, reviewed
   together. `WasaAffirmationForm` deleted; carry-forward means an
   unchanged certificate is not re-uploaded; `exit_gate` still refuses an
   expired `valid_upto`.
2. **Cross-application reads are cross-programme only**: an exit's claimed
   milestones are staff-approved rows on its own application; only
   cross-programme reuse (an HCX exit accepting the product's ABDM M1)
   reads a sibling enrollment.
3. **Post-approval updates of an `updatable` form skip the cycle** via
   `record()` (legacy "edit integration profile"). Safe: grants are
   decision-time ceilings — widening grants nothing until the next reviewed
   exit decision. Refused while an exit is undecided — same application,
   same lock.
4. **Accepted user-visible deltas**: no stored "start review" pickup
   (claiming = first recommendation); no per-cycle WASA re-affirmation
   (submitting the cycle is the affirmation); rejection is never terminal
   (deliberate policy change); milestones need staff review before an exit
   claims them (§6); withdrawal preserved everywhere, incl. post-approval.
5. **Later, not priority**: per-organisation submission rate limit —
   terminal rejection was accidentally a spam control.
6. **Exits live on the enrollment application** (2026-09-02): workflow =
   programme; `ABDMExit` deleted, `ExitClaim` repeatable + reviewed.
   Traded away, ruled acceptable: no retraction of a pending exit (future
   `retract` verb if NHA asks); grants sit on the withdrawable container —
   **facts from withdrawn enrollments stay reusable by default**
   (predicates read approved rows across the product's applications
   including withdrawn ones; NHA to confirm; narrowing = one-line predicate
   filter). Bought: one exit in flight = the partial unique; the ceiling
   race = the application lock; "exit N" = derived run grouping (§2).
7. **Verb split + one home for derived facts** (2026-09-02): `save`/`submit`
   own the review cycle, `record` the review-skipping writes — each user
   act its own endpoint (§3). Derived facts single-homed in
   `workflow/derived.py` (§2); promotion to a cached column only under
   measurement.

## 9. Blast radius

Deleted outright:

- `workflow/definitions.py` — `TransitionSpec`, `ActorKind`, most of `Workflow`
- `workflow/engine.py` — the interpreter, hook/guard registries, `clear_*`
- `workflow/models.py` — `WorkflowTransition`; `WorkflowReview` → new `Review`
- `applications/models.py` — `Application.state`, `round`,
  `ApplicationState`, `RESTING_STATES`, `is_current`, the state index
- `workflow/guards.py` — `registration_complete` (circular now: the thing it
  checked for is the thing being submitted); `exit_gate` moves to the
  programme as an `ExitClaim` check

New / rewritten:

- `workflow/verbs.py` (save / submit / record / review / withdraw),
  `workflow/derived.py` (every derived display fact, §2),
  `workflow/authz.py` (`can()` + `OwnershipBackend`), slim `Workflow` and
  `FormDefinition` bases, permission minting at migrate
- `integrations/` — `ProvisioningAttempt`; **`tasks.py` is the riskiest
  single rewrite**: the chain currently drives engine transitions and gates
  teardown on application state; it re-anchors on `ProvisionedResource` +
  attempts
- console — queue and review screens re-unit from Application to
  FormSubmission; one review screen (verdict + comment + Recommend/Decide
  per `can()`, decision fields on a binding approve); exit history renders
  cycle runs segmented at APPROVED boundaries ("exit N" is derived, §2)
- dashboard selectors — counts by application type and derived status,
  read only through `workflow/derived.py` annotations, never template loops
- `Application.submitted_at` (admin column, console sort) derives from the
  registration submission
- everything reading `application.state`, `round` or `WorkflowTransition`
  re-points at form statuses and cycles: ~61 files (measured) including
  templates (`state_variant`, `get_state_display`, queue round column) and
  the seed command; expect roughly a third of the 751 tests to move

Build order, each step shippable: models + verbs + authz with tests →
port the programme definitions → provisioning attempt log → console →
delete the old engine and tables.
