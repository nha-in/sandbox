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
from typing import Any
from typing import cast

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from storages.backends.s3 import S3Storage

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


#: rendered in the browser rather than downloaded. Deliberately a small
#: allowlist: the other accepted kinds are spreadsheets no browser renders, and
#: `inline` on anything script-bearing would be a stored-XSS route.
VIEWABLE_INLINE = frozenset({"application/pdf"})


def _download_storage() -> S3Storage:
    """Storage bound to the endpoint the *browser* can reach.

    SigV4 covers the Host header, so a URL signed against the compose-internal
    `minio:9000` is not merely inconvenient — rewriting its host invalidates the
    signature. It has to be signed against the public name to begin with.
    """
    public = settings.AWS_S3_PUBLIC_ENDPOINT_URL
    if not public or public == settings.AWS_S3_ENDPOINT_URL:
        return cast("S3Storage", document_storage())
    configured = cast("dict[str, dict[str, Any]]", settings.STORAGES)
    return S3Storage(**dict(configured["evidence"]["OPTIONS"], endpoint_url=public))


def download_url(document: ApplicationDocument) -> str:
    """A short-lived presigned GET; the bucket itself is private.

    A PDF opens in the browser's viewer, anything else downloads. Both the
    type and the filename are ours: `content_type` is derived from the magic
    bytes at upload, never from what the client claimed, and the filename has
    already been through a regex that keeps quotes and separators out of this
    header.
    """
    disposition = "inline" if document.content_type in VIEWABLE_INLINE else "attachment"
    return _download_storage().url(
        document.storage_key,
        parameters={
            "ResponseContentDisposition": (
                f'{disposition}; filename="{document.filename}"'
            ),
            "ResponseContentType": document.content_type,
        },
    )
