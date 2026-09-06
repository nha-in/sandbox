"""One approved ABDM application, and the actors who get it there.

The provisioning chain used to hang off `sandbox/workflow/`, so its tests drove
it with `transition(...)` and a Django permission codename. Both are gone: the
chain is an `ActionResult.effects` entry now, which means these tests have to
walk the application through the registry's own actions, and the reviewer holds
a `ReviewRole` rather than a `Permission`.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.models import ReviewRole
from sandbox.experiences.models import ReviewRoleAssignment
from sandbox.experiences.registry import registry
from sandbox.experiences.services import create_application
from sandbox.experiences.services import perform_application_action
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

APPLICATION_TYPE = "abdm_production_access"

#: What `ApprovalForm` would have cleaned. Passed straight to the action, since
#: these tests are about what approval *causes*, not about its form.
APPROVAL = {
    "production_client_id": "PROD-CLIENT-1001",
    "approved_milestones": ["m1", "m2", "m3"],
    "certificate_reference": "CERT-2026-1001",
    "note": "All evidence verified.",
}

REJECTION = {
    "reason": "security_gap",
    "details": "The assessment did not cover the gateway callback host.",
    "note": "Reapply after a fresh assessment.",
}


@pytest.fixture
def owner(db):
    return UserFactory.create(email="owner@vendor.in")


@pytest.fixture
def reviewer(db):
    """A decision maker: the standing role that carries approve, reject and retry."""
    user = UserFactory.create(email="reviewer@nha.gov.in")
    ReviewRoleAssignment.objects.create(
        user=user,
        role=ReviewRole.objects.get(key="decision_maker"),
    )
    return user


@pytest.fixture
def application(owner):
    organisation = OrganisationFactory(onboarded=True, name="Sunrise Health Systems")
    Membership.objects.create(
        organisation=organisation,
        user=owner,
        role=Role.OWNER,
    )
    application = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
    )
    for form_definition in registry.get(APPLICATION_TYPE).forms:
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_definition.key,
            data={},
            submitted_by=owner,
        )
    return application


@pytest.fixture
def under_review(application, owner, reviewer):
    """Submitted and picked up — one action short of every decision."""
    perform_application_action(
        application=application,
        action_key="submit",
        user=owner,
    )
    perform_application_action(
        application=application,
        action_key="start_review",
        user=reviewer,
    )
    application.refresh_from_db()
    return application


@pytest.fixture
def approve(under_review, reviewer, django_capture_on_commit_callbacks):
    """Approve, running the chain the approval schedules on commit."""

    def _approve():
        with django_capture_on_commit_callbacks(execute=True):
            perform_application_action(
                application=under_review,
                action_key="approve",
                user=reviewer,
                cleaned_data={
                    **APPROVAL,
                    "effective_date": timezone.localdate(),
                },
            )
        under_review.refresh_from_db()
        return under_review

    return _approve


@pytest.fixture
def reject(under_review, reviewer, django_capture_on_commit_callbacks):
    """Reject, running the teardown the rejection schedules on commit."""

    def _reject():
        with django_capture_on_commit_callbacks(execute=True):
            perform_application_action(
                application=under_review,
                action_key="reject",
                user=reviewer,
                cleaned_data=REJECTION,
            )
        under_review.refresh_from_db()
        return under_review

    return _reject
