"""Evidence attached to a form submission.

Documents hang off the submission, not the application, because a certificate
evidences one revision's claim: a resubmission after a rejection needs a fresh
audit, and the old one must stay readable against the round it was filed for.

A repeated `sha256` is deliberately *not* refused. A WASA certificate is
reusable — a valid one covers a minor change, and a web/iOS/Android release is
three certificates for one product — so the console warns and a human decides
(plan/10-production-truth.md).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction

from sandbox.applications.models import ApplicationDocument
from sandbox.applications.validators import validate_upload
from sandbox.applications.validators import validate_upload_set

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from django.core.files.storage import Storage
    from django.core.files.uploadedfile import UploadedFile

    from sandbox.applications.models import ApplicationFormSubmission
    from sandbox.users.models import User

    #: raises if the bytes are not safe to keep
    AvScanner = Callable[[str, bytes], None]


def document_storage() -> Storage:
    """Resolved per call so tests can swap the backend."""
    return storages["evidence"]


#: name -> scanner. Registered by whatever provides AV in this deployment;
#: an empty registry means nothing is scanned, which is a deployment choice.
_SCANNERS: dict[str, AvScanner] = {}


def register_scanner(name: str, handler: AvScanner) -> None:
    _SCANNERS[name] = handler


def clear_scanners() -> None:
    """For tests — never call this from application code."""
    _SCANNERS.clear()


def _scan(filename: str, content: bytes) -> None:
    for scanner in _SCANNERS.values():
        scanner(filename, content)


@transaction.atomic
def attach_documents(
    *,
    submission: ApplicationFormSubmission,
    uploads: Sequence[UploadedFile],
    kind: str,
    actor: User,
) -> list[ApplicationDocument]:
    """Store evidence of one kind against one submission revision.

    Replaces whatever of that kind was carried forward: re-uploading is how you
    correct a document, and two current files of the same kind would leave the
    reviewer to guess which one is being claimed.
    """
    if not uploads:
        return []

    validate_upload_set(list(uploads))
    storage = document_storage()
    stored: list[ApplicationDocument] = []

    for upload in uploads:
        content_type = validate_upload(upload)
        content = upload.read()
        upload.seek(0)
        _scan(upload.name or "", content)

        # UUID key, so knowing one document's location reveals no others.
        key = f"applications/{submission.external_id}/{uuid.uuid4()}"
        storage.save(key, ContentFile(content))

        stored.append(
            ApplicationDocument(
                submission=submission,
                kind=kind,
                storage_key=key,
                filename=upload.name or "",
                content_type=content_type,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                uploaded_by=actor,
            ),
        )

    submission.documents.filter(kind=kind, deleted=False).update(deleted=True)
    return ApplicationDocument.objects.bulk_create(stored)


def download_url(document: ApplicationDocument) -> str:
    """A short-lived presigned GET; the bucket itself is private."""
    return document_storage().url(document.storage_key)
