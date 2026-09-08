"""An application one action short of a decision, and the two actors involved.

`approve` and `reject` are callables rather than fixtures because what they
cause is the subject: a test arms a fake to fail, *then* calls them. Both run
the chain the decision schedules, since an effect that stayed queued would
prove nothing.

The chain used to hang off `sandbox/workflow/`, so its tests drove it with
`transition(...)` and a Django permission codename. Both are gone — the chain
is an `ActionResult.effects` entry, and the reviewer holds a `ReviewRole`.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from sandbox.experiences.services import perform_application_action
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.experiences.tests.factories import sandbox_access_under_review
from sandbox.users.tests.factories import UserFactory

#: What `ApprovalForm` would have cleaned. Passed straight to the action, since
#: these tests are about what approval *causes*, not about its form.
APPROVAL = {
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
    return review_role_holder("decision_maker", email="reviewer@nha.gov.in")


@pytest.fixture
def under_review(owner, reviewer):
    """A sandbox access submitted and picked up — one action short of the
    approval that provisions (plan 12 §1.2)."""
    return sandbox_access_under_review(owner, reviewer)


@pytest.fixture
def approve(under_review, reviewer, django_capture_on_commit_callbacks):
    """Approve, running the chain the approval schedules on commit."""

    def _approve():
        # The first gate has no evidence review; approving it is the whole step.
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
