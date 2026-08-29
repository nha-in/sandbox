"""Server-side upload validation. The client is never believed about anything.

Legacy checked the filename extension only (`GeneralUtils.isFileTypeSupported`),
so renaming `payload.exe` to `report.pdf` passed. Here the extension must agree
with the bytes.

CSV is the honest exception: it has no signature, so it can only be checked
negatively — it must not *be* something else, and it must decode as text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django.conf import settings

from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

#: bytes each format must start with. CSV is absent on purpose.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),  # OLE2 compound file
    ".xlsx": (b"PK\x03\x04",),  # zip container
}

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".csv": "text/csv",
}

#: what a .csv must not start with — the spoofing check that legacy lacked
_BINARY_SIGNATURES: tuple[bytes, ...] = (
    b"%PDF-",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    b"PK\x03\x04",
    b"MZ",  # dos/windows executable
    b"\x7fELF",  # linux executable
    b"\xca\xfe\xba\xbe",  # mach-o fat binary / java class
    b"\xfe\xed\xfa\xce",  # mach-o
    b"\x89PNG",
    b"\xff\xd8\xff",  # jpeg
    b"GIF8",
    b"\x1f\x8b",  # gzip
    b"Rar!",
    b"7z\xbc\xaf\x27\x1c",
    b"<?xml",  # could carry an external-entity payload
    b"<",  # html/svg — scripts render if ever served inline
)

# Mirrors legacy's REGEX_FOR_FILE_NAME, with the unescaped dot fixed. Keeps
# separators, quotes and control characters out of Content-Disposition.
_FILENAME = re.compile(r"^[A-Za-z0-9 ()_-]{1,200}\.[A-Za-z0-9]{1,10}$")

_SNIFF_BYTES = 8


def _extension(filename: str) -> str:
    _, _, suffix = filename.rpartition(".")
    return f".{suffix.lower()}"


def validate_upload(upload: UploadedFile) -> str:
    """Check one file and return the content type we are prepared to record.

    Raises `DomainError` — never trusts `upload.content_type`, which is
    whatever the browser felt like sending.
    """
    filename = upload.name or ""
    if not _FILENAME.match(filename):
        message = f"{filename or 'file'} has a name we cannot accept"
        raise DomainError(message, code="invalid_filename")

    extension = _extension(filename)
    if extension not in settings.UPLOAD_ALLOWED_EXTENSIONS:
        allowed = ", ".join(settings.UPLOAD_ALLOWED_EXTENSIONS)
        message = f"{filename} is not one of {allowed}"
        raise DomainError(message, code="invalid_type")

    if upload.size is None or upload.size > settings.UPLOAD_MAX_BYTES:
        limit = settings.UPLOAD_MAX_BYTES // (1024 * 1024)
        message = f"{filename} is larger than {limit} MB"
        raise DomainError(message, code="too_large")

    if not upload.size:
        message = f"{filename} is empty"
        raise DomainError(message, code="empty_file")

    _check_signature(filename, extension, upload)
    return _CONTENT_TYPES[extension]


def _check_signature(filename: str, extension: str, upload: UploadedFile) -> None:
    head = upload.read(_SNIFF_BYTES)
    upload.seek(0)

    expected = _SIGNATURES.get(extension)
    if expected is not None:
        if not head.startswith(expected):
            message = f"{filename} is not really {extension[1:].upper()}"
            raise DomainError(message, code="content_mismatch")
        return

    _check_is_text(filename, head, upload)


def _check_is_text(filename: str, head: bytes, upload: UploadedFile) -> None:
    """The CSV path: prove it is not a binary wearing a .csv name."""
    if head.startswith(_BINARY_SIGNATURES):
        message = f"{filename} is not really CSV"
        raise DomainError(message, code="content_mismatch")

    sample = upload.read(min(upload.size or 0, settings.UPLOAD_MAX_BYTES))
    upload.seek(0)
    if b"\x00" in sample:
        message = f"{filename} is not really CSV"
        raise DomainError(message, code="content_mismatch")
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        message = f"{filename} is not valid UTF-8 text"
        raise DomainError(message, code="content_mismatch") from exc


def validate_upload_set(uploads: list[UploadedFile]) -> None:
    """Caps that apply to the batch rather than to any one file."""
    if len(uploads) > settings.UPLOAD_MAX_FILES:
        message = f"attach at most {settings.UPLOAD_MAX_FILES} files"
        raise DomainError(message, code="too_many_files")

    total = sum(upload.size or 0 for upload in uploads)
    if total > settings.UPLOAD_MAX_TOTAL_BYTES:
        limit = settings.UPLOAD_MAX_TOTAL_BYTES // (1024 * 1024)
        message = f"the attachments total more than {limit} MB"
        raise DomainError(message, code="too_large")
