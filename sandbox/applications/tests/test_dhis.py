"""Registering on DHIS.

The button is live only for a solution type an exit actually approved, with
every milestone that type's matrix row demands. These assert that gate, and
that recording a claim blocks nothing — DHIS enforces claim-once itself, so
refusing a second claim here would be us guessing at another system's state.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from sandbox.applications.services import open_exit
from sandbox.organisations.mixins import organisation_query
from sandbox.programmes.abdm import SolutionType
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow import engine

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302
TWO_CLAIMS = 2


@pytest.fixture
def client_(member):
    client = Client()
    client.force_login(member)
    return client


def _url(application) -> str:
    route = reverse(
        "applications:dhis",
        kwargs={"external_id": application.external_id},
    )
    return f"{route}?{organisation_query(application.product.organisation)}"


def _approve_exit(application, member, covers, approved_types):
    """Take an exit all the way to APPROVED, so it produces a real grant."""
    # an out-of-range reference: the factory sequence and the DB counter clash
    application.reference = "SBX-1999-00001"
    application.save(update_fields=["reference"])

    exit_application = open_exit(product=application.product, applicant=member)
    engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": covers, "summary": "Built and tested."},
        user=member,
    )
    exit_application.state = "UNDER_REVIEW"
    exit_application.save(update_fields=["state"])

    approver = UserFactory.create(is_staff=True)
    approver.user_permissions.add(
        Permission.objects.get(codename="approve_abdm"),
    )
    engine.transition(
        application=exit_application,
        action="APPROVE",
        actor=approver,
        decision_data={"approved_solution_types": approved_types},
    )


def _rows(response) -> dict[str, dict]:
    return {row["value"]: row for row in response.context["rows"]}


def test_nothing_is_enabled_before_an_exit_is_approved(client_, application):
    response = client_.get(_url(application))

    assert response.status_code == HTTP_OK
    assert not any(row["enabled"] for row in response.context["rows"])


def test_an_approved_type_with_its_whole_matrix_row_covered_is_enabled(
    client_,
    application,
    member,
):
    _approve_exit(
        application,
        member,
        covers=["M1", "M2"],
        approved_types=[SolutionType.LMIS.value],
    )

    rows = _rows(client_.get(_url(application)))

    # LMIS needs M1 and M2, and both were covered
    assert rows[SolutionType.LMIS.value]["enabled"]


def test_an_approved_type_missing_a_milestone_stays_shut(
    client_,
    application,
    member,
):
    """HMIS needs M1, M2 and M3. Approving the type is not enough on its own."""
    _approve_exit(
        application,
        member,
        covers=["M1", "M2"],
        approved_types=[SolutionType.HMIS.value],
    )

    rows = _rows(client_.get(_url(application)))

    assert not rows[SolutionType.HMIS.value]["enabled"]


def test_a_covered_type_the_admin_did_not_approve_stays_shut(
    client_,
    application,
    member,
):
    """Coverage is not consent: the admin's approved list is its own gate."""
    _approve_exit(
        application,
        member,
        covers=["M1", "M2"],
        approved_types=[],
    )

    rows = _rows(client_.get(_url(application)))

    assert not rows[SolutionType.LMIS.value]["enabled"]


def test_recording_a_claim_never_blocks_a_second_one(client_, application, member):
    _approve_exit(
        application,
        member,
        covers=["M1", "M2"],
        approved_types=[SolutionType.LMIS.value],
    )

    for _ in range(TWO_CLAIMS):
        response = client_.post(
            _url(application),
            {"solution_type": SolutionType.LMIS.value},
        )
        assert response.status_code == HTTP_FOUND

    claims = application.submissions.filter(form_key="DHIS_CLAIM")
    assert claims.count() == TWO_CLAIMS
    # repeatable forms are pure history: none of them is ever "current"
    assert not claims.filter(is_current=True).exists()
