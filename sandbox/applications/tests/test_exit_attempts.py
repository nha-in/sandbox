"""Attempts: what an exit said each time it went to NHA.

The history screens promise "this is what NHA saw". These assert the two things
that promise rests on — that an attempt is reconstructed from the moment it was
sent rather than from the round column, and that a later edit cannot rewrite an
earlier attempt.
"""

from __future__ import annotations

import pytest
from django.http import Http404

from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import attempt_or_404
from sandbox.applications.selectors import attempts
from sandbox.applications.selectors import exit_history
from sandbox.applications.services import open_exit
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow import engine
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition

pytestmark = pytest.mark.django_db


@pytest.fixture
def provisioned():
    application = ApplicationFactory.create(
        reference="SBX-1998-00001",
        state=ApplicationState.PROVISIONED,
    )
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=application.applicant,
    )
    return application


@pytest.fixture
def exiting(provisioned):
    return open_exit(product=provisioned.product, applicant=provisioned.applicant)


@pytest.fixture
def reviewer(provisioned):
    return UserFactory.create(is_staff=True)


def _claim(exit_application, owner, covers, summary):
    return engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": covers, "summary": summary},
        user=owner,
    )


def test_an_exit_never_sent_has_no_attempts(exiting, provisioned):
    _claim(exiting, provisioned.applicant, ["M1"], "first draft")

    assert attempts(exiting) == []


def test_an_attempt_holds_the_answers_as_they_stood_when_it_was_sent(
    exiting,
    provisioned,
    reviewer,
):
    """A send-back is answered by editing the claim while the exit is still on
    the old round, so grouping by round files that edit under the attempt it
    replaced. Only the timestamp gets this right."""
    owner = provisioned.applicant
    _claim(exiting, owner, ["M1"], "as first sent")
    _mark_sent(exiting, owner)
    _record(exiting, reviewer, "SEND_BACK", "fix the scan")
    _claim(exiting, owner, ["M1", "M2"], "as second sent")
    _mark_sent(exiting, owner)

    history = attempts(exiting)

    assert [attempt.ordinal for attempt in history] == [2, 1]
    first = history[-1]
    assert first.forms["EXIT_CLAIM"].data["summary"] == "as first sent"
    assert first.forms["EXIT_CLAIM"].data["covers"] == ["M1"]


def test_a_later_edit_cannot_rewrite_an_earlier_attempt(
    exiting,
    provisioned,
    reviewer,
):
    owner = provisioned.applicant
    _claim(exiting, owner, ["M1"], "as first sent")
    _mark_sent(exiting, owner)
    before = attempt_or_404(exiting, 1).forms["EXIT_CLAIM"].data
    _record(exiting, reviewer, "SEND_BACK", "fix the scan")

    _claim(exiting, owner, ["M1", "M2", "M3"], "rewritten later")

    assert attempt_or_404(exiting, 1).forms["EXIT_CLAIM"].data == before


def test_an_attempt_carries_only_the_reviews_that_answered_it(
    exiting,
    provisioned,
    reviewer,
):
    owner = provisioned.applicant
    _claim(exiting, owner, ["M1"], "first")
    _mark_sent(exiting, owner)
    _record(exiting, reviewer, "SEND_BACK", "fix the scan")
    _claim(exiting, owner, ["M1"], "second")
    _mark_sent(exiting, owner)
    _record(exiting, reviewer, "REJECT", "not ready")
    history = attempts(exiting)

    assert [review.comment for review in history[-1].reviews] == ["fix the scan"]
    assert [review.comment for review in history[0].reviews] == ["not ready"]


def test_an_attempt_names_what_became_of_it(exiting, provisioned, reviewer):
    owner = provisioned.applicant
    _claim(exiting, owner, ["M1"], "first")
    _mark_sent(exiting, owner)
    _record(exiting, reviewer, "SEND_BACK", "fix the scan")

    assert attempt_or_404(exiting, 1).outcome == "SEND_BACK"


def test_an_attempt_still_with_nha_has_no_outcome(exiting, provisioned):
    owner = provisioned.applicant
    _claim(exiting, owner, ["M1"], "first")
    _mark_sent(exiting, owner)

    assert attempt_or_404(exiting, 1).outcome == ""


def test_an_ordinal_that_was_never_sent_is_not_found(exiting, provisioned):
    _claim(exiting, provisioned.applicant, ["M1"], "first")
    _mark_sent(exiting, provisioned.applicant)

    with pytest.raises(Http404):
        attempt_or_404(exiting, 2)


def test_history_holds_the_in_flight_exit_too(exiting, provisioned):
    """Answering a send-back means reading the exit you are still inside."""
    assert exit_history(provisioned.product) == [exiting]


def _mark_sent(exit_application, owner):
    """Record a SUBMIT without going through the gate.

    The gate demands milestones, evidence and an unexpired certificate, none of
    which these tests are about — they are about what an attempt *remembers*.
    """
    WorkflowTransition.objects.create(
        application=exit_application,
        from_state=exit_application.state,
        to_state="SUBMITTED",
        action="SUBMIT",
        actor=owner,
    )
    exit_application.state = "SUBMITTED"
    exit_application.save(update_fields=["state"])


def _record(exit_application, reviewer, action, comment):
    WorkflowReview.objects.create(
        application=exit_application,
        reviewer=reviewer,
        round=exit_application.round,
        decision=action,
        comment=comment,
    )
    WorkflowTransition.objects.create(
        application=exit_application,
        from_state=exit_application.state,
        to_state="SENT_BACK" if action == "SEND_BACK" else "REJECTED",
        action=action,
        actor=reviewer,
    )
    exit_application.state = "SENT_BACK" if action == "SEND_BACK" else "REJECTED"
    exit_application.round += 1
    exit_application.save(update_fields=["state", "round"])
