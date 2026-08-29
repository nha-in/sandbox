"""Declaration services — the only writers of declaration rows and stored files.

A submission is one transaction: release the claims it replaces, insert the new
declaration, store and fingerprint its files. The partial unique index on
`DeclarationMilestone` is what makes that safe against two concurrent
submissions; the release and the insert are never separately visible.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.utils import timezone

from sandbox.applications.models import ApplicationState
from sandbox.audit.services import emit
from sandbox.declarations.models import SETTLED_STATES
from sandbox.declarations.models import Declaration
from sandbox.declarations.models import DeclarationDocument
from sandbox.declarations.models import DeclarationKind
from sandbox.declarations.models import DeclarationMilestone
from sandbox.declarations.validators import validate_upload
from sandbox.declarations.validators import validate_upload_set
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable
    from collections.abc import Sequence

    from django.core.files.storage import Storage
    from django.core.files.uploadedfile import UploadedFile

    from sandbox.applications.models import Application
    from sandbox.catalog.models import Milestone
    from sandbox.users.models import User

    AvScanner = Callable[[str, bytes], None]

#: name -> scanner. Empty in v0: the interface exists so a real scanner can be
#: registered at app-ready time without touching this module.
_SCANNERS: dict[str, AvScanner] = {}


def register_scanner(name: str, handler: AvScanner) -> None:
    """Register a scanner; it must raise `DomainError` to reject a file."""
    _SCANNERS[name] = handler


def clear_scanners() -> None:
    """For tests — never call this from application code."""
    _SCANNERS.clear()


def _scan(filename: str, content: bytes) -> None:
    for scanner in _SCANNERS.values():
        scanner(filename, content)


def declaration_storage() -> Storage:
    """The private bucket. Never `default` — nothing else may serve these."""
    return storages["declarations"]


def _require_provisioned(application: Application) -> None:
    if application.state != ApplicationState.PROVISIONED:
        message = f"cannot declare while the application is {application.state}"
        raise DomainError(message, code="illegal_state")


def _claim_milestones(
    *,
    declaration: Declaration,
    application: Application,
    kind: str,
    milestones: Sequence[Milestone],
) -> None:
    """Move the current claims aside and take them for `declaration`.

    Refuses to displace a settled claim: superseding an APPROVED exit would
    quietly retract evidence that a milestone reached production.
    """
    current = list(
        DeclarationMilestone.objects.select_for_update()
        .filter(
            application=application,
            kind=kind,
            milestone__in=milestones,
            superseded_by__isnull=True,
        )
        .select_related("milestone", "declaration"),
    )

    settled = [
        claim for claim in current if claim.declaration.state in SETTLED_STATES
    ]
    if settled:
        keys = ", ".join(sorted(claim.milestone.key for claim in settled))
        message = f"{keys} has already been approved and cannot be redeclared"
        raise DomainError(message, code="already_settled")

    if current:
        DeclarationMilestone.objects.filter(
            pk__in=[claim.pk for claim in current],
        ).update(superseded_by=declaration)

    DeclarationMilestone.objects.bulk_create(
        [
            DeclarationMilestone(
                declaration=declaration,
                milestone=milestone,
                application=application,
                kind=kind,
            )
            for milestone in milestones
        ],
    )


def _store_documents(
    *,
    declaration: Declaration,
    uploads: Sequence[UploadedFile],
    actor: User,
) -> list[DeclarationDocument]:
    validate_upload_set(list(uploads))
    storage = declaration_storage()
    stored: list[DeclarationDocument] = []

    for upload in uploads:
        content_type = validate_upload(upload)
        content = upload.read()
        upload.seek(0)
        _scan(upload.name or "", content)

        # UUID key, so knowing one document's location reveals no others.
        key = f"declarations/{declaration.external_id}/{uuid.uuid4()}"
        storage.save(key, ContentFile(content))

        stored.append(
            DeclarationDocument(
                declaration=declaration,
                storage_key=key,
                filename=upload.name or "",
                content_type=content_type,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                uploaded_by=actor,
            ),
        )

    return DeclarationDocument.objects.bulk_create(stored)


@transaction.atomic
def submit_milestone_declaration(  # noqa: PLR0913 - a declaration form's worth of fields
    *,
    application: Application,
    milestone: Milestone,
    payload: dict[str, Any] | None = None,
    files: Sequence[UploadedFile] = (),
    actor: User,
    started_on: datetime.date | None = None,
    completed_on: datetime.date | None = None,
) -> Declaration:
    """Declare one milestone complete, with optional evidence."""
    _require_provisioned(application)
    _check_dates(started_on, completed_on)

    declaration = Declaration.objects.create(
        application=application,
        kind=DeclarationKind.MILESTONE,
        payload=payload or {},
        started_on=started_on,
        completed_on=completed_on,
        declared_by=actor,
    )
    _claim_milestones(
        declaration=declaration,
        application=application,
        kind=DeclarationKind.MILESTONE,
        milestones=[milestone],
    )
    documents = _store_documents(
        declaration=declaration,
        uploads=files,
        actor=actor,
    )

    emit(
        "declaration.milestone_submitted",
        obj=declaration,
        actor=actor,
        data={
            "reference": application.reference,
            "milestone": milestone.key,
            "documents": len(documents),
        },
    )
    return declaration


@transaction.atomic
def submit_exit_declaration(
    *,
    application: Application,
    milestones: Sequence[Milestone],
    payload: dict[str, Any] | None = None,
    files: Sequence[UploadedFile] = (),
    actor: User,
) -> Declaration:
    """Declare readiness to take `milestones` to production. Consumed by A8.

    The milestone set is recorded rather than derived, because it means
    "complete at the time of exit" — recomputing it later would answer a
    different question.
    """
    _require_provisioned(application)
    if not milestones:
        message = "an exit declaration must name at least one milestone"
        raise DomainError(message, code="no_milestones")

    declaration = Declaration.objects.create(
        application=application,
        kind=DeclarationKind.EXIT,
        payload=payload or {},
        declared_by=actor,
    )
    _claim_milestones(
        declaration=declaration,
        application=application,
        kind=DeclarationKind.EXIT,
        milestones=milestones,
    )
    documents = _store_documents(
        declaration=declaration,
        uploads=files,
        actor=actor,
    )

    emit(
        "declaration.exit_submitted",
        obj=declaration,
        actor=actor,
        data={
            "reference": application.reference,
            "milestones": sorted(milestone.key for milestone in milestones),
            "documents": len(documents),
        },
    )
    return declaration


def _check_dates(
    started_on: datetime.date | None,
    completed_on: datetime.date | None,
) -> None:
    today = timezone.localdate()
    for label, value in (("start", started_on), ("completion", completed_on)):
        if value is not None and value > today:
            message = f"the {label} date is in the future"
            raise DomainError(message, code="invalid_date")

    if started_on and completed_on and completed_on < started_on:
        message = "the completion date is before the start date"
        raise DomainError(message, code="invalid_date")


def download_url(document: DeclarationDocument) -> str:
    """A presigned GET; the backend's `querystring_expire` sets the lifetime."""
    return declaration_storage().url(document.storage_key)
