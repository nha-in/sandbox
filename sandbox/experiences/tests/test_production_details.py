"""§9.5: the production client id, recorded by the review team after approval.

Legacy's equivalent is a bespoke super-admin screen that overwrites the value
with no audit row. Here it is a form, so the revision chain and the
`FORM_SUBMITTED` event carry the correction and its history for free.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from sandbox.experiences.abdm.forms import ProductionDetailsForm
from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.models import EventKind
from sandbox.experiences.registry import registry
from sandbox.experiences.services import application_context
from sandbox.experiences.services import perform_application_action
from sandbox.experiences.services import save_form_submission
from sandbox.experiences.tests.factories import application_under_review
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_production_access"
FORM_KEY = "production_details"
COMPLETE_PERCENT = 100


@pytest.fixture
def owner(db):
    return UserFactory(email="owner@vendor.in")


@pytest.fixture
def reviewer(db):
    return review_role_holder()


@pytest.fixture
def approved(owner, reviewer):
    application = application_under_review(owner, reviewer)
    perform_application_action(
        application=application,
        action_key="review_evidence",
        user=reviewer,
        cleaned_data={
            "hard_copy_received_on": timezone.localdate(),
            "verified_milestones": [],
        },
    )
    perform_application_action(
        application=application,
        action_key="approve",
        user=reviewer,
        cleaned_data={
            "approved_milestones": ["m1"],
            "effective_date": timezone.localdate(),
            "certificate_reference": "CERT-2026-1001",
            "note": "Verified.",
        },
    )
    application.refresh_from_db()
    return application


def bound(**overrides):
    data = {
        "production_client_id": "PROD-CLIENT-1001",
        "issued_on": timezone.localdate().isoformat(),
    }
    data.update(overrides)
    form = ProductionDetailsForm(data=data)
    assert form.is_valid(), form.errors
    return form


def record(application, user, **overrides):
    return save_form_submission(
        application=application,
        form_key=FORM_KEY,
        form=bound(**overrides),
        user=user,
    )


def test_the_review_team_records_the_production_client_after_approval(
    approved,
    reviewer,
):
    submission = record(approved, reviewer)

    assert submission.data["production_client_id"] == "PROD-CLIENT-1001"
    assert submission.revision == 1
    assert submission.submitted_by == reviewer


def test_the_applicant_never_sees_the_form(approved, owner, reviewer):
    definition = registry.get(APPLICATION_TYPE)
    form_definition = definition.get_form(FORM_KEY)

    applicant_context = application_context(approved, owner)
    assert form_definition.is_applicable(applicant_context) is False
    assert form_definition.is_visible(applicant_context) is False
    visible = [
        state.definition.key
        for state in definition.form_states(applicant_context)
        if state.visible
    ]
    assert FORM_KEY not in visible

    reviewer_context = application_context(approved, reviewer)
    assert form_definition.is_visible(reviewer_context) is True


def test_the_applicant_cannot_record_it(approved, owner):
    with pytest.raises(PermissionDenied):
        record(approved, owner)


def test_it_cannot_be_recorded_before_the_decision(owner, reviewer):
    under_review = application_under_review(owner, reviewer)

    with pytest.raises(PermissionDenied):
        record(under_review, reviewer)


def test_a_correction_keeps_the_previous_value(approved, reviewer):
    record(approved, reviewer)
    corrected = record(approved, reviewer, production_client_id="PROD-CLIENT-2002")

    rows = ApplicationFormSubmission.objects.filter(
        application=approved,
        form_key=FORM_KEY,
    ).order_by("revision")
    assert [row.revision for row in rows] == [1, 2]
    assert rows[0].data["production_client_id"] == "PROD-CLIENT-1001"
    assert rows[0].is_current is False
    assert corrected.data["production_client_id"] == "PROD-CLIENT-2002"
    assert corrected.is_current is True


def test_every_correction_is_audited(approved, reviewer):
    record(approved, reviewer)
    record(approved, reviewer, production_client_id="PROD-CLIENT-2002")

    events = approved.events.filter(
        kind=EventKind.FORM_SUBMITTED,
        payload__form_key=FORM_KEY,
    ).order_by("created_at")

    assert [event.payload["revision"] for event in events] == [1, 2]
    assert {event.actor for event in events} == {reviewer}


def test_it_is_not_part_of_the_applicant_s_progress(approved, reviewer):
    before = approved.metadata["required_forms"]

    record(approved, reviewer)

    approved.refresh_from_db()
    assert approved.metadata["required_forms"] == before
    assert approved.metadata["progress_percent"] == COMPLETE_PERCENT


def test_a_future_issue_date_is_refused():
    form = ProductionDetailsForm(
        data={
            "production_client_id": "PROD-CLIENT-1001",
            "issued_on": (timezone.localdate() + timedelta(days=1)).isoformat(),
        },
    )

    assert form.is_valid() is False
    assert "issued_on" in form.errors
