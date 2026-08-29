# A7 — Declarations + document uploads (validation, S3, sha256)

> **Lane** A — Backend: domain & workflow · **Phase** V0.4 Milestones, exit & pilot readiness
> **Depends on** [A3](A3-applications-model.md), [A1](A1-catalog-app.md) (milestone FK)
> **Unblocks** [A8](A8-exit-workflow.md) (exit docs reuse this pipeline), [C8](C8-milestone-exit-forms.md)
> **Refs** [03-database.md §3.4](../03-database.md) · [05-security.md §3.2](../05-security.md) · [01-backend.md §3.3](../01-backend.md)

## In plain words

Once an integrator has credentials, they prove progress by **declaring milestones** ("we completed patient registration flow") and attaching evidence files. This ticket stores those declarations as rows and builds the portal's one safe file-upload pipeline: files are checked (type, size, content), stored in a private bucket nobody can browse, fingerprinted (sha256), and downloadable only by the owning organisation through expiring links. The exit-to-production paperwork ([A8](A8-exit-workflow.md)) reuses the same pipeline.

## Background

Integrators progress through sandbox milestones by **self-declaration** (v0 has no conformance service — verified evidence comes later). The legacy system modelled this as a column-per-milestone `self_declaration` table (schema change per new track) and had no principled upload handling. v2 makes milestone completions **rows** — adding a track becomes data — and builds one hardened upload pipeline that exit documents ([A8](A8-exit-workflow.md)) reuse.

## What to build

### Deliverables

| #   | Deliverable                                                                                  | Where                                |
| --- | -------------------------------------------------------------------------------------------- | ------------------------------------ |
| 1   | `Declaration` + `DeclarationMilestone` + `DeclarationDocument` models + migrations           | `sandbox/declarations/models.py`     |
| 2   | Upload validation (extension + sniffed magic bytes + size) with settings-driven caps         | `sandbox/declarations/validators.py` |
| 3   | Storage wiring: django-storages private bucket (MinIO in compose), UUID storage keys, sha256 | `sandbox/declarations/services.py`   |
| 4   | `submit_milestone_declaration` / `submit_exit_declaration` services                          | same                                 |
| 5   | Org-scoped presigned-download view + URL                                                     | `sandbox/declarations/views.py`      |
| 6   | AV-scan hook registry (no-op v0) · coverage + timeline selectors                             | services/selectors                   |
| 7   | Tests: abuse cases (oversize, spoofed content), sha256, download authz                       | `sandbox/declarations/tests/`        |

### Models

`declarations_declaration` (extends the shared base model — [03-database.md §3.1](../03-database.md)):

| Field                         | Type             | Constraints / notes                                              |
| ----------------------------- | ---------------- | ---------------------------------------------------------------- |
| `application`                 | FK → application |                                                                  |
| `kind`                        | char + CHECK     | `MILESTONE \| EXIT`                                              |
| `state`                       | char + CHECK     | `SUBMITTED \| APPROVED \| REJECTED` — v0 only writes SUBMITTED   |
| `started_on` / `completed_on` | date, null       | real columns, not payload — reporting filters and sorts on these |
| `payload`                     | JSONB            | the rest of the declaration form content                         |
| `declared_by`                 | FK → user        |                                                                  |
| —                             |                  | CHECK: `completed_on >= started_on` when both present            |

`declarations_declaration_milestone` — which milestones a declaration covers. Not a `BaseModel`: never addressed externally, and it must not carry `deleted`, because supersession is not deletion.

| Field           | Type                   | Constraints / notes                                                 |
| --------------- | ---------------------- | ------------------------------------------------------------------- |
| `declaration`   | FK → declaration       |                                                                     |
| `milestone`     | FK → catalog_milestone |                                                                     |
| `application`   | FK → application       | denormalized; a partial index sees only its own table               |
| `kind`          | char + CHECK           | denormalized, same reason                                           |
| `superseded_by` | FK → declaration, null | null = this is the current claim                                    |
| —               |                        | `UNIQUE (application, kind, milestone) WHERE superseded_by IS NULL` |

`declarations_document`:

| Field          | Type             | Constraints / notes                                 |
| -------------- | ---------------- | --------------------------------------------------- |
| `declaration`  | FK → declaration |                                                     |
| `storage_key`  | char             | UUID-based — non-derivable                          |
| `filename`     | char(255)        | original name, for display only                     |
| `content_type` | char(100)        | sniffed server-side — never trusted from the client |
| `size`         | int              | bytes                                               |
| `sha256`       | char(64)         | computed server-side on receipt                     |
| `uploaded_by`  | FK → user        |                                                     |

### Upload pipeline (the security-sensitive part)

- Server-side validation: extension **and** magic bytes and size caps from settings.
- Storage via django-storages → **private** S3 bucket (compose: MinIO; tests: `moto`).
- Downloads only through an org-scoped view issuing **presigned GETs** — no public URLs, no direct bucket exposure.
- AV-scan hook registry stubbed (`register_scanner`, no scanner in v0).

### Decisions taken while building

- **`kind=SELF` dropped.** Legacy's `self_declaration` header fields were dead: the frontend writes only `completeMil` ([sandbox-declaration-form.js L495](../../../sandbox-website/src/pages/user-dashboard/components/sandbox-declaration-form.js)), which is exactly the set of v2 MILESTONE rows. `willCompleteMil`, `workingOn` and `tentativeDate` have no producer anywhere.
- **Milestone coverage is a join table, not an FK.** An exit covers the _set_ of milestones going to production while carrying one document bundle — legacy stored that set as a CSV in `sd_exit.integration_detail`. A nullable FK cannot hold it, and a JSONB list cannot be constrained.
- **Supersession, not soft delete.** A resubmission stamps `superseded_by` on the claims it replaces, inside the same transaction that inserts the new ones. The replaced declaration and its documents stay fully readable; only its claim on the milestone moves. Using `deleted` would have hidden history behind the soft-delete manager by default.
- **Claims are per kind.** Declaring M1 and exiting M1 are separate claims, so the unique index carries `kind`.
- **An APPROVED claim cannot be superseded** — otherwise a resubmission silently retracts evidence that a milestone reached production. Rejection frees nothing; the resubmission does.
- **Formats follow legacy** (`pdf/xls/xlsx/csv`). PDF, XLS and XLSX are verified by signature; CSV has none, so it is checked negatively (not a known binary, no NULs, decodes as UTF-8) — which still stops the `.exe`-renamed case.
- **Open question 3 is answered by the legacy code**, though not yet by NHA: [utils.js L514](../../../sandbox-website/src/constants/utils.js) resolves an exit record _per milestone_ from its `integration_detail`, and `getBySdIdOrderByCreatedDateDesc` returns many exits per integrator. This model supports repeatable per-milestone exits without committing [A8](A8-exit-workflow.md) to changing the application state machine.

### Services & selectors

```python
# declarations/services.py — atomic; audited
def submit_milestone_declaration(*, application, milestone, payload, files, actor,
                                 started_on=None, completed_on=None) -> Declaration:
    """Guard: application must be PROVISIONED. Supersedes the previous claim,
    validates + stores files, computes sha256."""

def submit_exit_declaration(*, application, milestones, payload, files, actor) -> Declaration: ...  # consumed by A8

# declarations/selectors.py
def milestone_coverage(application) -> QuerySet[DeclarationMilestone]: ...  # current claims only
def declaration_timeline(application) -> QuerySet[Declaration]: ...        # everything, newest first
```

- Route-gate row for the presigned-download GET — wrong org 404s. The upload POST arrives with [C8](C8-milestone-exit-forms.md), which owns the forms.

## Acceptance criteria

- [x] Upload validation tested: oversize, wrong extension, spoofed content (`.exe` as `.pdf` and as `.csv`) all rejected server-side.
- [x] sha256 recorded and verified in tests; storage keys non-derivable.
- [x] Downloads: org member gets presigned GET; wrong org 404; anonymous → login.
- [x] A milestone has one current claim per kind; superseding an approved claim is refused.
- [x] Milestone declaration guarded on PROVISIONED state; audited.
- [x] Works offline via compose MinIO and `moto` in tests; mypy/ruff clean.

## Out of scope (deferred)

Conformance packs/runs/evidence gating (P4/P5) · WSO2 `get_usage` corroboration panel (P4) · actual AV integration (hook only) · **CSV formula-injection neutralisation (P3** — reviewers open these in Excel; tracked in [01-backend.md §5](../01-backend.md)**)**.
