"""§6 D1: what NHA requires before an exit application may be submitted."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from sandbox.experiences.abdm.gates import exit_gate_blockers
from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.registry import registry
from sandbox.experiences.services import application_context
from sandbox.experiences.services import create_application
from sandbox.experiences.services import perform_application_action
from sandbox.experiences.tests.factories import gate_data
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_production_access"


@pytest.fixture
def owner(db):
    return UserFactory(email="owner@vendor.in")


@pytest.fixture
def ready(owner):
    """Every form complete and the gate satisfied — one action from submitting."""
    organisation = OrganisationFactory(onboarded=True)
    Membership.objects.create(organisation=organisation, user=owner, role=Role.OWNER)
    application = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
    )
    for form_definition in registry.get(APPLICATION_TYPE).forms:
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_definition.key,
            data=gate_data().get(form_definition.key, {}),
            submitted_by=owner,
        )
    return application


def _blockers(application, owner):
    return exit_gate_blockers(application_context(application, owner))


def _amend(application, form_key, **changes):
    submission = application.submissions.get(form_key=form_key)
    submission.data = {**submission.data, **changes}
    submission.save(update_fields=["data"])


def test_a_complete_application_clears_the_gate(ready, owner):
    assert _blockers(ready, owner) == ()

    perform_application_action(application=ready, action_key="submit", user=owner)
    ready.refresh_from_db()

    assert ready.status == "submitted"


def test_functional_testing_evidence_is_required(ready, owner):
    _amend(ready, "conformance_evidence", functional_certificate_number="")

    assert "functional testing agency" in str(_blockers(ready, owner)[0])


def test_the_internal_demonstration_is_required(ready, owner):
    """Only the internal NHA demo gates submission — the HTC demo is a review
    step, so it must not appear here (§3.2)."""
    _amend(ready, "conformance_evidence", demonstration_date="")

    assert "internal ABDM demonstration" in str(_blockers(ready, owner)[0])


def test_the_production_callback_url_is_required(ready, owner):
    """NHA: "The Callback URL must be specified when submitting the Exit Form"."""
    _amend(ready, "technical_readiness", production_callback_url="")

    assert "callback URL" in str(_blockers(ready, owner)[0])


@pytest.mark.parametrize("certification_type", ["iso_27001", "soc_2", "other"])
def test_a_certification_that_is_not_safe_to_host_does_not_clear_the_gate(
    ready,
    owner,
    certification_type,
):
    """The form is complete either way. NHA asks for a specific artefact."""
    _amend(ready, "security_certification", certification_type=certification_type)

    assert "Safe-to-Host" in str(_blockers(ready, owner)[0])


@pytest.mark.parametrize("certification_type", ["wasa", "cert_in_audit"])
def test_stqc_and_cert_in_are_the_same_artefact(ready, owner, certification_type):
    """§3.2: STQC or CERT-In empanelled, both yielding a Safe-to-Host
    certificate."""
    _amend(ready, "security_certification", certification_type=certification_type)

    assert _blockers(ready, owner) == ()


def test_an_expired_safe_to_host_certificate_does_not_clear_the_gate(ready, owner):
    submission = ready.submissions.get(form_key="security_certification")
    submission.valid_until = timezone.localdate() - timedelta(days=1)
    submission.save(update_fields=["valid_until"])

    assert "Safe-to-Host" in str(_blockers(ready, owner)[0])


def test_the_gate_refuses_the_submission_itself(ready, owner):
    """Not only the availability check — the action refuses too."""
    _amend(ready, "conformance_evidence", demonstration_date="")

    with pytest.raises(PermissionDenied):
        perform_application_action(application=ready, action_key="submit", user=owner)
