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
from sandbox.applications.selectors import exit_in_flight
from sandbox.applications.tests.conftest import upload
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.mixins import organisation_query
from sandbox.programmes.abdm import DocumentKind
from sandbox.workflow import engine

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302
HTTP_NOT_FOUND = 404
THREE_DOCUMENTS = 3
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
):
    response = client_.get(_url("applications:milestones", application))

    assert response.status_code == HTTP_OK
    # the programme defines them now, so the list does not depend on seed data
    listed = [row.key for row in response.context["rows"]]
    assert listed == ["m1", "m2", "m3", "phr", "health_locker"]
    assert response.context["declared_count"] == 0


def test_a_milestone_behind_its_prerequisite_is_listed_but_locked(
    client_,
    organisation,
    application,
):
    response = client_.get(_url("applications:milestones", application))

    rows = {row.key: row for row in response.context["rows"]}
    assert rows["m1"].unlocked
    # M2 requires M1; the row still shows, so the path is visible before it opens
    assert not rows["m2"].unlocked
    assert rows["m2"].blocked_by


def test_another_organisations_application_is_404_not_403(
    client_,
    milestone,
    db,
):
    """Scoping is the whole authorization here. A 403 would confirm that the
    application exists, which A2 forbids."""
    theirs = ApplicationFactory.create(state=ApplicationState.PROVISIONED)

    response = client_.get(_url("applications:milestones", theirs))

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
        _url("applications:declare_milestone", application, key=milestone),
        {
            "started_on": "2026-01-05",
            "completed_on": "2026-02-05",
            "notes": "Linked three ABHA numbers end to end.",
            "documents": [upload()],
        },
    )

    assert response.status_code == HTTP_FOUND
    submission = application.submissions.get(form_key="MILESTONE_M1")
    assert submission.is_current
    assert submission.data["notes"] == "Linked three ABHA numbers end to end."


def test_declaring_twice_supersedes_rather_than_duplicates(
    client_,
    organisation,
    application,
    milestone,
):
    """The designed path: come back next month and re-declare the same
    milestone against the same application."""
    url = _url("applications:declare_milestone", application, key=milestone)
    client_.post(url, {"notes": "First attempt."})
    client_.post(url, {"notes": "Corrected."})

    claims = application.submissions.filter(form_key="MILESTONE_M1")
    assert claims.count() == TWO_CLAIMS
    current = claims.filter(is_current=True)
    assert current.count() == 1
    assert current.get().data["notes"] == "Corrected."


def test_a_future_completion_date_is_shown_as_a_form_error(
    client_,
    organisation,
    application,
    milestone,
):
    """The rule lives in the form. The screen surfaces it, never restates it."""
    response = client_.post(
        _url("applications:declare_milestone", application, key=milestone),
        {"completed_on": "2099-01-01"},
    )

    assert response.status_code == HTTP_OK
    assert not application.submissions.filter(form_key="MILESTONE_M1").exists()
    assert "future" in str(response.context["form"].errors)


def test_an_unknown_milestone_key_is_404(client_, organisation, application):
    response = client_.get(
        _url("applications:declare_milestone", application, key="not-a-milestone"),
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
        _url("applications:declare_milestone", application, key=milestone),
        {"notes": "Trying anyway."},
    )

    assert response.status_code == HTTP_OK
    assert not application.submissions.filter(form_key="MILESTONE_M1").exists()


# Exit


def test_exit_is_locked_until_something_is_declared(
    client_,
    organisation,
    application,
):
    response = client_.get(_url("applications:exit", application))

    assert response.context["is_locked"] is True
    assert response.context["declared_covers"] == []


def _declare_m1(application):
    engine.submit_form(
        application=application,
        form_key="MILESTONE_M1",
        cleaned_data={},
        user=application.applicant,
    )


def test_exit_offers_only_the_milestones_already_declared(
    client_,
    application,
    milestone,
):
    """The gate refuses to exit an undeclared milestone, so offering one would
    be a form that cannot be submitted."""
    _declare_m1(application)

    response = client_.get(_url("applications:exit", application))

    assert response.context["declared_covers"] == [
        ("M1", "M1 — ABHA creation & verification"),
    ]


def test_saving_the_claim_opens_an_exit_application(mock_s3, client_, application):
    """The exit is its own application, anchored to the product."""
    _declare_m1(application)

    response = client_.post(
        _url("applications:exit", application),
        {
            "step": "claim",
            "covers": ["M1"],
            "summary": "Two HIPs live, consent flows exercised.",
            DocumentKind.FUNCTIONAL_TEST_REPORT: upload(),
            DocumentKind.UNDERTAKING: upload(),
            DocumentKind.GSTIN_CERTIFICATE: upload(),
        },
    )

    assert response.status_code == HTTP_FOUND
    exit_application = exit_in_flight(application.product)
    assert exit_application is not None
    assert exit_application.workflow_key == "ABDM_EXIT"
    # the sandbox application is untouched: it is not the thing exiting
    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED
    claim = exit_application.submissions.get(form_key="EXIT_CLAIM")
    assert claim.data["covers"] == ["M1"]
    assert claim.documents.filter(deleted=False).count() == THREE_DOCUMENTS


def test_a_fully_evidenced_exit_reaches_review(mock_s3, client_, application):
    _declare_m1(application)
    url = _url("applications:exit", application)
    client_.post(
        url,
        {
            "step": "claim",
            "covers": ["M1"],
            "summary": "Two HIPs live.",
            DocumentKind.FUNCTIONAL_TEST_REPORT: upload(),
            DocumentKind.UNDERTAKING: upload(),
            DocumentKind.GSTIN_CERTIFICATE: upload(),
        },
    )
    client_.post(
        url,
        {
            "step": "wasa",
            "start": "2026-01-01",
            "valid_upto": "2027-01-01",
            DocumentKind.AUDIT_CERTIFICATE: upload(),
        },
    )

    response = client_.post(url, {"step": "submit"})

    assert response.status_code == HTTP_FOUND
    exit_application = exit_in_flight(application.product)
    assert exit_application is not None
    assert exit_application.state == "SUBMITTED"


def test_an_exit_with_no_evidence_is_refused_and_the_state_does_not_move(
    mock_s3,
    client_,
    application,
):
    """The gate needs every required document, so submitting without them is
    refused — and the exit stays where the integrator can fix it."""
    _declare_m1(application)
    url = _url("applications:exit", application)
    client_.post(
        url,
        {"step": "claim", "covers": ["M1"], "summary": "Nothing attached."},
    )
    client_.post(
        url,
        {"step": "wasa", "start": "2026-01-01", "valid_upto": "2027-01-01"},
    )

    response = client_.post(url, {"step": "submit"}, follow=True)

    assert response.status_code == HTTP_OK
    assert any("evidence" in str(m).lower() for m in response.context["messages"])
    exit_application = exit_in_flight(application.product)
    assert exit_application is not None
    assert exit_application.state == ApplicationState.DRAFT


def test_an_exit_cannot_cover_a_milestone_that_was_never_declared(
    mock_s3,
    client_,
    application,
):
    """The choices offered are the declared ones, so a hand-crafted POST is the
    only way here — and the form still refuses it."""
    _declare_m1(application)

    response = client_.post(
        _url("applications:exit", application),
        {"step": "claim", "covers": ["M3"], "summary": "Trying anyway."},
    )

    assert response.status_code == HTTP_OK
    assert response.context["claim_form"].errors
    assert exit_in_flight(application.product) is None
