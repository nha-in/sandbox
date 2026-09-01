"""Upload abuse cases. Legacy trusted the filename; these prove we don't."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from sandbox.applications.tests.conftest import CSV
from sandbox.applications.tests.conftest import PDF
from sandbox.applications.tests.conftest import XLS
from sandbox.applications.tests.conftest import XLSX
from sandbox.applications.validators import validate_upload
from sandbox.applications.validators import validate_upload_set
from sandbox.utils.errors import DomainError

WINDOWS_EXECUTABLE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 40


def _file(name, content, content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("report.pdf", PDF, "application/pdf"),
        ("book.xlsx", XLSX, None),
        ("book.xls", XLS, "application/vnd.ms-excel"),
        ("rows.csv", CSV, "text/csv"),
    ],
)
def test_every_allowed_format_is_accepted(name, content, expected):
    result = validate_upload(_file(name, content))
    if expected:
        assert result == expected


def test_the_recorded_content_type_ignores_what_the_client_claimed():
    """The browser's Content-Type is attacker-controlled; ours is derived."""
    sent_as_pdf = _file("rows.csv", CSV, content_type="application/pdf")
    assert validate_upload(sent_as_pdf) == "text/csv"


def test_an_executable_renamed_to_pdf_is_rejected():
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("invoice.pdf", WINDOWS_EXECUTABLE))
    assert exc.value.code == "content_mismatch"


def test_an_executable_renamed_to_csv_is_rejected():
    """CSV has no signature, so it is checked for not being something else."""
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("rows.csv", WINDOWS_EXECUTABLE))
    assert exc.value.code == "content_mismatch"


def test_html_renamed_to_csv_is_rejected():
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("rows.csv", b"<script>alert(1)</script>"))
    assert exc.value.code == "content_mismatch"


def test_binary_content_in_a_csv_is_rejected():
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("rows.csv", b"id,name\n1,\x00\x01\x02"))
    assert exc.value.code == "content_mismatch"


def test_a_pdf_renamed_to_xlsx_is_rejected():
    """Both are allowed types; the extension must still match the bytes."""
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("book.xlsx", PDF))
    assert exc.value.code == "content_mismatch"


def test_a_disallowed_extension_is_rejected():
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("payload.exe", WINDOWS_EXECUTABLE))
    assert exc.value.code == "invalid_type"


@pytest.mark.parametrize(
    "name",
    [
        "report.pdf\r\nX-Injected: 1",
        'quote".pdf',
        "no-extension",
    ],
)
def test_dangerous_filenames_are_rejected(name):
    with pytest.raises(DomainError) as exc:
        validate_upload(_file(name, PDF))
    assert exc.value.code in {"invalid_filename", "invalid_type"}


def test_a_traversal_filename_is_stripped_to_its_basename():
    """Django basenames `UploadedFile.name`; assert it, don't assume it."""
    upload = _file("../../etc/passwd.pdf", PDF)
    validate_upload(upload)
    assert upload.name == "passwd.pdf"


def test_an_oversize_file_is_rejected(settings):
    settings.UPLOAD_MAX_BYTES = 16
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("report.pdf", PDF))
    assert exc.value.code == "too_large"


def test_an_empty_file_is_rejected():
    with pytest.raises(DomainError) as exc:
        validate_upload(_file("report.pdf", b""))
    assert exc.value.code == "empty_file"


def test_too_many_files_are_rejected(settings):
    settings.UPLOAD_MAX_FILES = 2
    with pytest.raises(DomainError) as exc:
        validate_upload_set([_file(f"r{n}.pdf", PDF) for n in range(3)])
    assert exc.value.code == "too_many_files"


def test_the_batch_total_is_capped_independently_of_each_file(settings):
    """Ten files under the per-file cap can still be too much in one request."""
    settings.UPLOAD_MAX_FILES = 10
    settings.UPLOAD_MAX_TOTAL_BYTES = len(PDF) * 2
    with pytest.raises(DomainError) as exc:
        validate_upload_set([_file(f"r{n}.pdf", PDF) for n in range(3)])
    assert exc.value.code == "too_large"


def test_validation_leaves_the_file_readable_from_the_start():
    """Sniffing must not consume the stream the caller is about to store."""
    upload = _file("report.pdf", PDF)
    validate_upload(upload)
    assert upload.read() == PDF
