"""Submission, supersession and storage."""

from __future__ import annotations

import datetime
import hashlib

import pytest
from django.utils import timezone

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.declarations import services
from sandbox.declarations.models import DeclarationDocument
from sandbox.declarations.models import DeclarationKind
from sandbox.declarations.models import DeclarationMilestone
from sandbox.declarations.models import DeclarationState
from sandbox.declarations.tests.conftest import CSV
from sandbox.declarations.tests.conftest import PDF
from sandbox.declarations.tests.conftest import upload
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.utils.errors import DomainError

pytestmark = pytest.mark.django_db

EXPECTED_MILESTONES = 2
EXPECTED_KEYS = 2


def _current(application, kind=DeclarationKind.MILESTONE):
    return DeclarationMilestone.objects.filter(
        application=application,
        kind=kind,
        superseded_by__isnull=True,
    )


def test_a_milestone_declaration_takes_a_claim(application, milestone, member):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    claim = _current(application).get()
    assert claim.declaration == declaration
    assert claim.milestone == milestone
    assert declaration.state == DeclarationState.SUBMITTED


def test_declaring_is_blocked_before_the_application_is_provisioned(
    application,
    milestone,
    member,
):
    application.state = ApplicationState.SUBMITTED
    application.save(update_fields=["state"])

    with pytest.raises(DomainError) as exc:
        services.submit_milestone_declaration(
            application=application,
            milestone=milestone,
            actor=member,
        )
    assert exc.value.code == "illegal_state"


def test_redeclaring_supersedes_the_previous_claim(
    application,
    milestone,
    member,
):
    first = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    second = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    assert _current(application).get().declaration == second
    superseded = DeclarationMilestone.objects.get(declaration=first)
    assert superseded.superseded_by == second


def test_a_superseded_declaration_is_still_readable(
    application,
    milestone,
    member,
):
    """Supersession marks the claim, never the declaration or its evidence."""
    first = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    first.state = DeclarationState.REJECTED
    first.save(update_fields=["state"])
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )

    first.refresh_from_db()
    assert first.deleted is False
    assert first.state == DeclarationState.REJECTED
    assert first.milestones.count() == 1


def test_an_approved_claim_cannot_be_superseded(application, milestone, member):
    """Otherwise a resubmission would quietly retract production approval."""
    approved = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    approved.state = DeclarationState.APPROVED
    approved.save(update_fields=["state"])

    with pytest.raises(DomainError) as exc:
        services.submit_milestone_declaration(
            application=application,
            milestone=milestone,
            actor=member,
        )
    assert exc.value.code == "already_settled"
    assert _current(application).get().declaration == approved


def test_a_rejected_claim_can_be_superseded(application, milestone, member):
    rejected = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    rejected.state = DeclarationState.REJECTED
    rejected.save(update_fields=["state"])

    replacement = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    assert _current(application).get().declaration == replacement


def test_an_exit_covers_several_milestones_with_one_document_bundle(
    mock_s3,
    application,
    milestone,
    other_milestone,
    member,
):
    declaration = services.submit_exit_declaration(
        application=application,
        milestones=[milestone, other_milestone],
        files=[upload()],
        actor=member,
    )

    assert declaration.milestones.count() == EXPECTED_MILESTONES
    assert declaration.documents.count() == 1


def test_an_exit_and_a_milestone_may_claim_the_same_milestone(
    application,
    milestone,
    member,
):
    """The claim is per kind: declaring M1 must not block exiting M1."""
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    services.submit_exit_declaration(
        application=application,
        milestones=[milestone],
        actor=member,
    )

    assert _current(application, DeclarationKind.MILESTONE).count() == 1
    assert _current(application, DeclarationKind.EXIT).count() == 1


def test_an_exit_must_name_a_milestone(application, member):
    with pytest.raises(DomainError) as exc:
        services.submit_exit_declaration(
            application=application,
            milestones=[],
            actor=member,
        )
    assert exc.value.code == "no_milestones"


def test_claims_do_not_cross_applications(
    application,
    organisation,
    milestone,
    member,
):
    """Two products of one org exit the same milestone independently."""
    other = ApplicationFactory.create(
        product=ProductFactory.create(organisation=organisation),
        applicant=member,
        state=ApplicationState.PROVISIONED,
    )

    services.submit_exit_declaration(
        application=application,
        milestones=[milestone],
        actor=member,
    )
    services.submit_exit_declaration(
        application=other,
        milestones=[milestone],
        actor=member,
    )

    assert _current(application, DeclarationKind.EXIT).count() == 1
    assert _current(other, DeclarationKind.EXIT).count() == 1


# Storage


def test_documents_are_fingerprinted_and_stored_under_a_uuid_key(
    mock_s3,
    application,
    milestone,
    member,
):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        files=[upload("evidence.pdf", PDF)],
        actor=member,
    )

    document = declaration.documents.get()
    assert document.sha256 == hashlib.sha256(PDF).hexdigest()
    assert document.size == len(PDF)
    assert document.filename == "evidence.pdf"
    assert document.content_type == "application/pdf"
    # non-derivable: nothing in the key comes from the filename
    assert "evidence" not in document.storage_key
    assert str(declaration.external_id) in document.storage_key

    with services.declaration_storage().open(document.storage_key) as stored:
        assert stored.read() == PDF


def test_two_identical_files_get_different_keys(
    mock_s3,
    application,
    milestone,
    member,
):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        files=[upload("a.pdf", PDF), upload("b.pdf", PDF)],
        actor=member,
    )
    keys = {document.storage_key for document in declaration.documents.all()}
    assert len(keys) == EXPECTED_KEYS


def test_a_rejected_file_stores_nothing_and_creates_no_declaration(
    mock_s3,
    application,
    milestone,
    member,
):
    """The whole submission is one transaction, files included."""
    with pytest.raises(DomainError):
        services.submit_milestone_declaration(
            application=application,
            milestone=milestone,
            files=[upload("good.pdf", PDF), upload("bad.pdf", b"MZ\x90\x00")],
            actor=member,
        )

    assert not application.declarations.exists()
    assert not DeclarationDocument.objects.exists()


def test_a_presigned_url_is_scoped_to_the_object_and_expires(
    mock_s3,
    application,
    milestone,
    member,
    settings,
):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        files=[upload()],
        actor=member,
    )
    url = services.download_url(declaration.documents.get())

    assert "X-Amz-Signature=" in url
    assert f"X-Amz-Expires={settings.UPLOAD_DOWNLOAD_URL_TTL_SECONDS}" in url


# The AV hook


def test_a_registered_scanner_can_reject_a_file(
    mock_s3,
    application,
    milestone,
    member,
):
    def reject(filename, content):
        message = f"{filename} looks infected"
        raise DomainError(message, code="infected")

    services.register_scanner("test", reject)

    with pytest.raises(DomainError) as exc:
        services.submit_milestone_declaration(
            application=application,
            milestone=milestone,
            files=[upload()],
            actor=member,
        )
    assert exc.value.code == "infected"
    assert not DeclarationDocument.objects.exists()


def test_no_scanner_is_registered_by_default(
    mock_s3,
    application,
    milestone,
    member,
):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        files=[upload()],
        actor=member,
    )
    assert declaration.documents.count() == 1


# Dates


def test_dates_are_recorded_as_columns(application, milestone, member):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
        started_on=datetime.date(2026, 1, 5),
        completed_on=datetime.date(2026, 2, 5),
    )
    assert declaration.started_on == datetime.date(2026, 1, 5)
    assert declaration.completed_on == datetime.date(2026, 2, 5)


def test_dates_are_optional(application, milestone, member):
    declaration = services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    assert declaration.started_on is None


def test_completion_before_start_is_rejected(application, milestone, member):
    with pytest.raises(DomainError) as exc:
        services.submit_milestone_declaration(
            application=application,
            milestone=milestone,
            actor=member,
            started_on=datetime.date(2026, 2, 5),
            completed_on=datetime.date(2026, 1, 5),
        )
    assert exc.value.code == "invalid_date"


def test_a_future_date_is_rejected(application, milestone, member):
    with pytest.raises(DomainError) as exc:
        services.submit_milestone_declaration(
            application=application,
            milestone=milestone,
            actor=member,
            completed_on=timezone.localdate() + datetime.timedelta(days=1),
        )
    assert exc.value.code == "invalid_date"


# Audit


def test_submissions_are_audited(mock_s3, application, milestone, member):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        files=[upload("rows.csv", CSV)],
        actor=member,
    )

    event = AuditEvent.objects.get(action="declaration.milestone_submitted")
    assert event.actor == member
    assert event.data["milestone"] == milestone.key
    assert event.data["documents"] == 1


def test_exit_submissions_are_audited(application, milestone, member):
    services.submit_exit_declaration(
        application=application,
        milestones=[milestone],
        actor=member,
    )

    event = AuditEvent.objects.get(action="declaration.exit_submitted")
    assert event.data["milestones"] == [milestone.key]
