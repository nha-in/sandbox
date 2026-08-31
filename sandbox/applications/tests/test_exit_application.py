"""Opening an exit, and attaching evidence to a revision.

An exit is its own application. These assert the two rules that makes possible
and the one it must not break: you cannot exit a product with no sandbox, a
second exit cannot open while one is in flight, and an approved exit must not
block the next one.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from sandbox.applications.documents import attach_documents
from sandbox.applications.models import ApplicationState
from sandbox.applications.services import open_exit
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.programmes.abdm import DocumentKind
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4 minimal"


def _upload(name: str = "audit.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


@pytest.fixture
def provisioned():
    # an explicit reference: the factory sequence and the DB counter both mint
    # SBX-2026-0000N and would otherwise collide on the unique index
    application = ApplicationFactory.create(
        reference="SBX-1999-00001",
        state=ApplicationState.PROVISIONED,
    )
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=application.applicant,
    )
    return application


def test_opening_an_exit_creates_its_own_application(provisioned):
    exit_application = open_exit(
        product=provisioned.product,
        applicant=provisioned.applicant,
    )

    assert exit_application.pk != provisioned.pk
    assert exit_application.workflow_key == "ABDM_EXIT"
    assert exit_application.state == ApplicationState.DRAFT
    assert exit_application.round == 1
    # anchored to the product, so it survives the sandbox application
    assert exit_application.product == provisioned.product


def test_opening_an_exit_twice_returns_the_one_in_flight(provisioned):
    first = open_exit(product=provisioned.product, applicant=provisioned.applicant)
    second = open_exit(product=provisioned.product, applicant=provisioned.applicant)

    assert first.pk == second.pk


def test_a_product_with_no_provisioned_sandbox_cannot_exit():
    draft = ApplicationFactory.create(state=ApplicationState.DRAFT)

    with pytest.raises(DomainError, match="no provisioned sandbox"):
        open_exit(product=draft.product, applicant=draft.applicant)


def test_a_product_with_no_application_at_all_cannot_exit():
    product = ProductFactory.create()

    with pytest.raises(DomainError, match="no provisioned sandbox"):
        open_exit(product=product, applicant=UserFactory.create())


def test_an_approved_exit_does_not_block_the_next_one(provisioned):
    """January's M1 exit is approved; September's M2 exit must still open."""
    first = open_exit(product=provisioned.product, applicant=provisioned.applicant)
    first.state = "APPROVED"
    first.save(update_fields=["state"])

    second = open_exit(product=provisioned.product, applicant=provisioned.applicant)

    assert second.pk != first.pk


def test_evidence_is_attached_to_the_revision_it_evidences(mock_s3, provisioned):
    exit_application = open_exit(
        product=provisioned.product,
        applicant=provisioned.applicant,
    )
    submission = engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": ["M1"], "summary": "ABHA verified."},
        user=provisioned.applicant,
    )

    stored = attach_documents(
        submission=submission,
        uploads=[_upload()],
        kind=DocumentKind.AUDIT_CERTIFICATE,
        actor=provisioned.applicant,
    )

    assert len(stored) == 1
    assert stored[0].submission == submission
    assert stored[0].sha256
    # the key reveals nothing about any other document
    assert stored[0].storage_key.startswith(f"applications/{submission.external_id}/")


def test_re_uploading_the_same_kind_replaces_it(mock_s3, provisioned):
    exit_application = open_exit(
        product=provisioned.product,
        applicant=provisioned.applicant,
    )
    submission = engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": ["M1"], "summary": "ABHA verified."},
        user=provisioned.applicant,
    )
    attach_documents(
        submission=submission,
        uploads=[_upload("first.pdf")],
        kind=DocumentKind.AUDIT_CERTIFICATE,
        actor=provisioned.applicant,
    )

    attach_documents(
        submission=submission,
        uploads=[_upload("corrected.pdf")],
        kind=DocumentKind.AUDIT_CERTIFICATE,
        actor=provisioned.applicant,
    )

    live = submission.documents.filter(deleted=False)
    assert [document.filename for document in live] == ["corrected.pdf"]
