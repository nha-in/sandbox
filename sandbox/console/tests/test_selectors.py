"""The reads behind the queue's ageing and the reviewer's flags."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.console.selectors import humanised_history
from sandbox.console.selectors import queue_rows
from sandbox.console.selectors import reviewer_flags
from sandbox.workflow.models import WorkflowTransition

pytestmark = pytest.mark.django_db


def _submitted(application, *, days_ago: int):
    transition = WorkflowTransition.objects.create(
        application=application,
        from_state=ApplicationState.DRAFT,
        to_state=ApplicationState.SUBMITTED,
        action="SUBMIT",
    )
    WorkflowTransition.objects.filter(pk=transition.pk).update(
        created_date=timezone.now() - timedelta(days=days_ago),
    )
    return transition


def test_a_row_ages_from_the_submission_not_the_draft():
    """A draft opened in March and sent yesterday has waited a day."""
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)
    _submitted(application, days_ago=3)

    (row,) = queue_rows([application])

    assert row.waiting_days == 3
    assert not row.is_over_target


def test_a_long_wait_is_marked_over_target(settings):
    settings.REVIEW_TARGET_DAYS = 7
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)
    _submitted(application, days_ago=11)

    (row,) = queue_rows([application])

    assert row.is_over_target


def test_an_unsubmitted_application_has_no_age():
    application = ApplicationFactory.create(state=ApplicationState.DRAFT)

    (row,) = queue_rows([application])

    assert row.waiting_days is None
    assert not row.is_over_target


def test_the_queue_says_what_is_being_asked_for():
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)

    (row,) = queue_rows([application])

    assert "Sandbox access" in str(row.asking_for)


def test_history_reads_as_sentences_but_keeps_the_triple():
    """The sentence is for the reviewer; the raw triple is the audit trail."""
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)
    _submitted(application, days_ago=1)

    (entry,) = humanised_history(application)

    assert str(entry.sentence) == "Submitted for review"
    assert entry.raw == "DRAFT → SUBMITTED · SUBMIT"


def test_an_unmapped_action_falls_back_to_its_name():
    """A new action must not render blank while nobody has written its sentence."""
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)
    WorkflowTransition.objects.create(
        application=application,
        from_state=ApplicationState.SUBMITTED,
        to_state=ApplicationState.SUBMITTED,
        action="SOMETHING_NEW",
    )

    (entry,) = humanised_history(application)

    assert str(entry.sentence) == "SOMETHING_NEW"


def test_a_first_round_exit_raises_no_flags():
    exit_application = ApplicationFactory.create(
        workflow_key="ABDM_EXIT",
        state="UNDER_REVIEW",
        registered=False,
    )

    assert reviewer_flags(exit_application) == []
