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

| # | Deliverable | Where |
|---|---|---|
| 1 | `Declaration` + `DeclarationDocument` models + migrations | `sandbox/declarations/models.py` |
| 2 | Upload validation (extension + sniffed MIME + size) with settings-driven caps | `sandbox/declarations/validators.py` |
| 3 | Storage wiring: django-storages private bucket (MinIO in compose), UUID storage keys, sha256 | `sandbox/declarations/services.py` |
| 4 | `submit_milestone_declaration` / `submit_exit_declaration` services | same |
| 5 | Org-scoped presigned-download view + URL | `sandbox/declarations/views.py` |
| 6 | AV-scan hook interface (no-op v0) · timeline selector | services/selectors |
| 7 | Tests: abuse cases (oversize, spoofed MIME), sha256, download authz | `sandbox/declarations/tests/` |

### Models

`declarations_declaration` (extends the shared base model — [03-database.md §3.1](../03-database.md)):

| Field | Type | Constraints / notes |
|---|---|---|
| `application` | FK → application | |
| `kind` | char + CHECK | `SELF \| EXIT \| MILESTONE` |
| `milestone` | FK → catalog_milestone, null | CHECK: required when kind=MILESTONE |
| `started_on` / `completed_on` | date, null | real columns, not payload — reporting filters and sorts on these |
| `payload` | JSONB | the rest of the declaration form content |
| `state` | char | |
| — | | `UNIQUE (application, milestone) WHERE deleted = false` where milestone is not null |

`declarations_document`:

| Field | Type | Constraints / notes |
|---|---|---|
| `declaration` | FK → declaration | |
| `storage_key` | char | UUID-based — non-derivable |
| `filename` | char(255) | original name, for display only |
| `content_type` | char(100) | sniffed server-side — never trusted from the client |
| `size` | int | bytes |
| `sha256` | char(64) | computed server-side on receipt |
| `uploaded_by` | FK → user | |

### Upload pipeline (the security-sensitive part)

- Server-side validation: extension **and** MIME (sniffed) and size caps from settings.
- Storage via django-storages → **private** S3 bucket (compose: MinIO or the fake storage backend for offline dev).
- Downloads only through an org-scoped/console-gated view issuing **presigned GETs** — no public URLs, no direct bucket exposure.
- AV-scan hook point stubbed (interface in place, no-op in v0).

### Services & selectors

```python
# declarations/services.py — atomic; audited
def submit_milestone_declaration(*, application, milestone, payload, files, actor) -> Declaration:
    """Guard: application must be PROVISIONED (via workflow).
    Validates + stores files, computes sha256."""

def submit_exit_declaration(*, application, payload, files, actor) -> Declaration: ...  # consumed by A8

# declarations/selectors.py
def declaration_timeline(application) -> QuerySet[Declaration]: ...  # dashboard + console detail
```

- Route-gate rows for every new URL (upload POST, presigned-download GET) — wrong org 404s.

## Acceptance criteria

- [ ] Upload validation tested: oversize, wrong extension, spoofed MIME (e.g. `.exe` as `application/pdf`) all rejected server-side.
- [ ] sha256 recorded and verified in tests; storage keys non-derivable.
- [ ] Downloads: org member gets presigned GET; wrong org 404; anonymous → login.
- [ ] Duplicate (application, milestone) declaration rejected.
- [ ] Milestone declaration guarded on PROVISIONED state; audited.
- [ ] Works offline via compose storage backend; mypy/ruff clean.

## Out of scope (deferred)

Conformance packs/runs/evidence gating (P4/P5) · WSO2 `get_usage` corroboration panel (P4) · actual AV integration (hook only).
