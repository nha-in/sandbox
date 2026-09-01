"""Deciding an exit in the console, through the engine.

The exit is its own application, so these assert the two things that makes
possible and the one it must never allow: the reviewer's buttons come from the
exit workflow, an approval carries its decision, and an approval without one
does not happen at all.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sandbox.applications.models import Application
from sandbox.applications.services import open_exit
from sandbox.applications.tests.factories import VALID_SANDBOX_DATA
from sandbox.programmes.abdm import SolutionType
from sandbox.workflow import engine
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview

pytestmark = pytest.mark.django_db

HTTP_FOUND = 302


@pytest.fixture
def under_review(application, member):
    # the factory sequence and the DB counter both mint SBX-2026-0000N, and
    # open_exit uses the counter
    application.reference = "SBX-1999-00001"
    application.save(update_fields=["reference"])
    exit_application = open_exit(product=application.product, applicant=member)
    engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": ["M1"], "summary": "Two HIPs live."},
        user=member,
    )
    exit_application.state = "UNDER_REVIEW"
    exit_application.save(update_fields=["state"])
    return exit_application


def detail_url(application):
    return reverse(
        "console:application_detail",
        kwargs={"external_id": application.external_id},
    )


def decide_url(application):
    return reverse("console:decide", kwargs={"external_id": application.external_id})


def test_the_reviewer_sees_the_claim_they_are_deciding_on(admin_client_, under_review):
    """Buttons without the claim would be a decision made blind."""
    body = admin_client_.get(detail_url(under_review)).content.decode()

    assert "Two HIPs live." in body
    assert "Exit to production" in body
    # the ceiling, on screen: only what was registered may be approved
    assert "HMIS" in body


def test_the_buttons_come_from_the_exit_workflow(admin_client_, under_review):
    response = admin_client_.get(detail_url(under_review))

    offered = {row["value"] for row in response.context["decision_actions"]}
    # Approve sits apart, with the EXIT_DECISION fields it writes
    assert offered == {"REJECT", "SEND_BACK"}
    assert response.context["approve_action"]["value"] == "APPROVE"
    assert response.context["is_exit"] is True


def test_an_exit_awaiting_pickup_offers_only_start_review(admin_client_, under_review):
    """SUBMITTED has one legal move and it is not a verdict. The page used to
    offer a review the service refuses and the approval fields beside it."""
    under_review.state = "SUBMITTED"
    under_review.save(update_fields=["state"])

    response = admin_client_.get(detail_url(under_review))

    assert response.context["can_start_review"] is True
    assert response.context["decision_actions"] == []
    assert response.context["approve_action"] is None
    assert response.context["can_review"] is False
    body = response.content.decode()
    assert "Start review" in body
    # never the raw action code at a person
    assert "START_REVIEW<" not in body


def test_an_exit_with_no_registered_types_says_so_instead_of_a_dead_form(
    admin_client_,
    under_review,
):
    """The ceiling is a required field. Empty, it can never validate — so the
    console explains it rather than rendering a form nobody can submit."""
    sandbox = Application.objects.get(
        product=under_review.product,
        workflow_key="ABDM",
    )
    engine.submit_form(
        application=sandbox,
        form_key="REGISTRATION",
        cleaned_data={**VALID_SANDBOX_DATA, "solution_types": []},
        user=sandbox.applicant,
    )

    response = admin_client_.get(detail_url(under_review))

    assert response.context["approval_blocked"] is True
    assert "cannot be approved" in response.content.decode()


def test_the_admin_may_only_approve_what_was_registered(admin_client_, under_review):
    """The registration is a ceiling: the admin may unpick, never widen."""
    response = admin_client_.get(detail_url(under_review))

    form = response.context["exit_review"]["decision_form"]
    offered = [
        value for value, _label in form.fields["approved_solution_types"].choices
    ]
    assert offered == [SolutionType.HMIS.value]


def test_approving_writes_the_decision_with_the_move(admin_client_, under_review):
    response = admin_client_.post(
        decide_url(under_review),
        {
            "action": "APPROVE",
            "approved_solution_types": [SolutionType.HMIS.value],
            "m1_on_v3_confirmed": "on",
        },
    )

    assert response.status_code == HTTP_FOUND
    under_review.refresh_from_db()
    assert under_review.state == "APPROVED"
    decision = under_review.submissions.get(form_key="EXIT_DECISION")
    assert decision.data["approved_solution_types"] == [SolutionType.HMIS.value]
    assert decision.data["m1_on_v3_confirmed"] is True


def test_approving_without_a_decision_moves_nothing(admin_client_, under_review):
    """The grant and the decision that authorised it are one write or neither."""
    admin_client_.post(decide_url(under_review), {"action": "APPROVE"})

    under_review.refresh_from_db()
    assert under_review.state == "UNDER_REVIEW"
    assert not under_review.submissions.filter(form_key="EXIT_DECISION").exists()


def test_approving_a_type_that_was_not_registered_is_refused(
    admin_client_,
    under_review,
):
    admin_client_.post(
        decide_url(under_review),
        {"action": "APPROVE", "approved_solution_types": [SolutionType.PHARMACY.value]},
    )

    under_review.refresh_from_db()
    assert under_review.state == "UNDER_REVIEW"


def test_sending_an_exit_back_records_the_reason_on_the_review(
    admin_client_,
    under_review,
):
    admin_client_.post(
        decide_url(under_review),
        {"action": "SEND_BACK", "comment": "The audit certificate has expired."},
    )

    under_review.refresh_from_db()
    assert under_review.state == "SENT_BACK"
    review = WorkflowReview.objects.get(application=under_review)
    assert review.decision == ReviewDecision.SEND_BACK
    assert review.comment == "The audit certificate has expired."
    # review-driven: the text lives on the review row, never on the transition
    assert under_review.transitions.latest("created_date").comment == ""
