"""The seed must be safe to re-run and scoped when it retires (A9)."""

from __future__ import annotations

import itertools

import pytest
from django.core.management import call_command

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.organisations.models import Organisation
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition

pytestmark = pytest.mark.django_db

SEED_PASSWORD = "seed-test-password"  # noqa: S105


@pytest.fixture(autouse=True)
def _bucket(mock_s3):
    """The seed uploads a real exit document, so it needs the bucket."""


def seed(**kwargs):
    call_command("seed_sandbox_demo", password=SEED_PASSWORD, verbosity=0, **kwargs)


def counts():
    return {
        "applications": Application.objects.count(),
        "transitions": WorkflowTransition.objects.count(),
        "reviews": WorkflowReview.objects.count(),
        "organisations": Organisation.objects.count(),
    }


def test_seed_covers_every_application_state(settings):
    settings.DEBUG = True
    seed()

    seeded = set(Application.objects.values_list("state", flat=True))

    assert seeded == set(ApplicationState.values)


def test_running_twice_creates_no_duplicates(settings):
    settings.DEBUG = True
    seed()
    first = counts()

    seed()

    assert counts() == first


def test_seeded_history_is_legal(settings):
    """Every seeded row was produced by transition(), so its trail must be real."""
    settings.DEBUG = True
    seed()

    for application in Application.objects.exclude(state=ApplicationState.DRAFT):
        trail = list(
            application.transitions.order_by("created_date").values_list(
                "from_state",
                "to_state",
            ),
        )
        assert trail, f"{application.reference} has no transition history"
        assert trail[0][0] == ApplicationState.DRAFT
        assert trail[-1][1] == application.state
        for (_, to_state), (next_from, _) in itertools.pairwise(trail):
            assert to_state == next_from, f"{application.reference} history has a gap"


def test_every_transition_left_an_audit_event(settings):
    settings.DEBUG = True
    seed()

    assert AuditEvent.objects.count() >= WorkflowTransition.objects.count()


def test_a_two_round_review_exists_for_the_console_tally(settings):
    settings.DEBUG = True
    seed()

    rounds = set(WorkflowReview.objects.values_list("round", flat=True))

    assert rounds == {1, 2}


def test_a_second_organisation_exists_for_wrong_org_checks(settings):
    settings.DEBUG = True
    seed()

    assert Organisation.objects.count() >= 2  # noqa: PLR2004


def test_fresh_retires_only_seeded_rows(settings):
    """A hand-made application must survive --fresh."""
    settings.DEBUG = True
    seed()
    manual = ApplicationFactory.create()

    seed(fresh=True)

    manual.refresh_from_db()
    assert not manual.deleted


def test_fresh_then_reseed_restores_every_state(settings):
    settings.DEBUG = True
    seed()

    seed(fresh=True)

    live = set(
        Application.objects.filter(deleted=False).values_list("state", flat=True),
    )
    assert live == set(ApplicationState.values)


def test_seeding_outside_debug_is_refused(settings):
    settings.DEBUG = False

    with pytest.raises(Exception, match="Refusing to seed"):
        seed()
