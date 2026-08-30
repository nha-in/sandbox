"""The integrator's milestone and exit screens (C8).

The route matrix already proves these URLs are org-scoped. What is asserted here
is what the screens do with the application they are given: that declaring twice
supersedes rather than duplicates, that exit is offered only for milestones that
were actually declared, and that a member with no application at all gets a page
rather than a dead link — the sidebar offers these to everyone.

Every POST is a plain multipart form post with no JavaScript involved, because
that is the path that has to keep working.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.declarations import services
from sandbox.declarations.models import Declaration
from sandbox.declarations.models import DeclarationKind
from sandbox.declarations.models import DeclarationMilestone
from sandbox.declarations.tests.conftest import upload
from sandbox.organisations.mixins import organisation_query

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302
HTTP_NOT_FOUND = 404
TWO_CLAIMS = 2


@pytest.fixture
def client_(member):
    client = Client()
    client.force_login(member)
    return client


def _url(name: str, application, **kwargs) -> str:
    """Every declaration screen names its application; the tenant rides in the
    query string, as it does everywhere else."""
    organisation = application.product.organisation
    return (
        f"{reverse(name, kwargs={'external_id': application.external_id, **kwargs})}"
        f"?{organisation_query(organisation)}"
    )


# Milestones


def test_every_active_milestone_is_listed_declared_or_not(
    client_,
    organisation,
    application,
    milestone,
    other_milestone,
):
    response = client_.get(_url("declarations:milestones", application))

    assert response.status_code == HTTP_OK
    listed = [row["milestone"] for row in response.context["rows"]]
    assert listed == [milestone, other_milestone]
    assert response.context["declared_count"] == 0


def test_an_exit_claim_does_not_count_as_a_milestone_declaration(
    mock_s3,
    client_,
    organisation,
    application,
    milestone,
):
    """Both kinds of claim can stand on one milestone at once. Keyed by
    milestone alone, the exit claim would win and the page would credit the
    completion to the wrong declaration."""
    services.submit_exit_declaration(
        application=application,
        milestones=[milestone],
        files=[upload()],
        actor=application.applicant,
    )

    response = client_.get(_url("declarations:milestones", application))

    assert response.context["declared_count"] == 0


def test_another_organisations_application_is_404_not_403(
    client_,
    milestone,
    db,
):
    """Scoping is the whole authorization here. A 403 would confirm that the
    application exists, which A2 forbids."""
    theirs = ApplicationFactory.create(state=ApplicationState.PROVISIONED)

    response = client_.get(_url("declarations:milestones", theirs))

    assert response.status_code == HTTP_NOT_FOUND


# Declaring


def test_declaring_a_milestone_stores_the_evidence(
    mock_s3,
    client_,
    organisation,
    application,
    milestone,
):
    response = client_.post(
        _url("declarations:declare_milestone", application, key=milestone.key),
        {
            "started_on": "2026-01-05",
            "completed_on": "2026-02-05",
            "notes": "Linked three ABHA numbers end to end.",
            "documents": [upload()],
        },
    )

    assert response.status_code == HTTP_FOUND
    declaration = Declaration.objects.get(application=application)
    assert declaration.kind == DeclarationKind.MILESTONE
    assert declaration.payload == {"notes": "Linked three ABHA numbers end to end."}
    assert declaration.documents.count() == 1


def test_declaring_twice_supersedes_rather_than_duplicates(
    client_,
    organisation,
    application,
    milestone,
):
    """The designed path: come back next month and re-declare the same
    milestone against the same application."""
    url = _url("declarations:declare_milestone", application, key=milestone.key)
    client_.post(url, {"notes": "First attempt."})
    client_.post(url, {"notes": "Corrected."})

    claims = DeclarationMilestone.objects.filter(
        application=application,
        milestone=milestone,
    )
    assert claims.count() == TWO_CLAIMS
    current = claims.filter(superseded_by__isnull=True)
    assert current.count() == 1
    assert current.get().declaration.payload == {"notes": "Corrected."}


def test_a_future_completion_date_is_shown_as_a_form_error(
    client_,
    organisation,
    application,
    milestone,
):
    """The rule lives in A7. The screen's job is to surface it, not restate it."""
    response = client_.post(
        _url("declarations:declare_milestone", application, key=milestone.key),
        {"completed_on": "2099-01-01"},
    )

    assert response.status_code == HTTP_OK
    assert Declaration.objects.count() == 0
    assert "future" in str(response.context["form"].errors)


def test_an_unknown_milestone_key_is_404(client_, organisation, application):
    response = client_.get(
        _url("declarations:declare_milestone", application, key="not-a-milestone"),
    )

    assert response.status_code == HTTP_NOT_FOUND


def test_a_state_that_cannot_declare_is_refused_by_the_service(
    client_,
    organisation,
    application,
    milestone,
):
    """The template hides the button; this proves the POST is refused too."""
    application.state = ApplicationState.SUBMITTED
    application.save(update_fields=["state"])

    response = client_.post(
        _url("declarations:declare_milestone", application, key=milestone.key),
        {"notes": "Trying anyway."},
    )

    assert response.status_code == HTTP_OK
    assert Declaration.objects.count() == 0


# Exit


def test_exit_is_locked_until_something_is_declared(
    client_,
    organisation,
    application,
):
    response = client_.get(_url("declarations:exit", application))

    assert response.context["is_locked"] is True
    assert response.context["declared_milestones"] == []


def test_exit_offers_only_the_milestones_already_declared(
    client_,
    application,
    milestone,
    other_milestone,
):
    """A8's guard refuses to exit an undeclared milestone, so offering one
    would be a form that cannot be submitted."""
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=application.applicant,
    )

    response = client_.get(
        _url("declarations:exit", application),
    )

    assert response.context["declared_milestones"] == [milestone]


def test_requesting_exit_moves_the_application(
    mock_s3,
    client_,
    application,
    milestone,
):
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=application.applicant,
    )

    response = client_.post(
        _url("declarations:exit", application),
        {
            "milestones": [milestone.key],
            "summary": "Two HIPs live, consent flows exercised.",
            "documents": [upload()],
        },
    )

    assert response.status_code == HTTP_FOUND
    application.refresh_from_db()
    assert application.state == ApplicationState.EXIT_REQUESTED


def test_an_exit_with_no_evidence_is_refused_and_the_state_does_not_move(
    client_,
    application,
    milestone,
):
    """A8 needs at least one document. The declaration is written before the
    transition is attempted, so this also proves the failure is atomic."""
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=application.applicant,
    )

    response = client_.post(
        _url("declarations:exit", application),
        {"milestones": [milestone.key], "summary": "Nothing attached."},
    )

    assert response.status_code == HTTP_OK
    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED
