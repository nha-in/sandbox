"""§4.2: what the applicant does not see on their own timeline."""

from __future__ import annotations

from http import HTTPStatus

import pytest
from django.urls import reverse
from django.utils import timezone

from sandbox.experiences.models import ApplicationEvent
from sandbox.experiences.models import EventKind
from sandbox.experiences.registry import registry
from sandbox.experiences.services import perform_application_action
from sandbox.experiences.tests.factories import application_under_review
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_production_access"


@pytest.fixture
def reviewer(db):
    return review_role_holder("decision_maker")


@pytest.fixture
def owner(db):
    return UserFactory(email="owner@vendor.in")


@pytest.fixture
def application(owner, reviewer):
    return application_under_review(owner, reviewer)


def test_an_event_is_public_unless_its_action_says_otherwise():
    assert ApplicationEvent(title="x").is_internal is False


def test_the_reviewer_only_actions_are_internal():
    """Their notes and operational retries are NHA's, not the applicant's."""
    definition = registry.get(APPLICATION_TYPE)

    assert definition.get_action("review_evidence").internal_event is True
    assert definition.get_action("retry_provisioning").internal_event is True
    assert definition.get_action("retry_deprovisioning").internal_event is True
    assert definition.get_action("approve").internal_event is False
    assert definition.get_action("raise_query").internal_event is False


def test_reviewing_writes_an_internal_event(application, reviewer):
    perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )

    assert application.events.get(action_key="review_evidence").is_internal is True


def test_the_applicant_timeline_hides_internal_events(client, application, reviewer):
    """The gap this closes: both detail views shared one unfiltered queryset."""
    ApplicationEvent.objects.create(
        application=application,
        kind=EventKind.ACTION,
        title="An internal note",
        is_internal=True,
    )
    client.force_login(application.created_by)

    html = client.get(
        reverse("experiences:detail", args=[application.reference]),
    ).content.decode()

    assert "An internal note" not in html


def test_the_console_timeline_shows_them(client, application, reviewer, enable_mfa):
    ApplicationEvent.objects.create(
        application=application,
        kind=EventKind.ACTION,
        title="An internal note",
        is_internal=True,
    )
    reviewer.is_staff = True
    reviewer.save(update_fields=["is_staff"])
    enable_mfa(reviewer)
    client.force_login(reviewer)

    response = client.get(
        reverse("ohc:application-detail", args=[application.reference]),
    )

    assert response.status_code == HTTPStatus.OK
    assert "An internal note" in response.content.decode()
