"""Milestone grants: what an approval leaves behind, and the one ordering."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.models import SubmissionStatus
from sandbox.experiences.registry import registry
from sandbox.experiences.services import application_context
from sandbox.experiences.services import perform_form_action
from sandbox.experiences.tests.factories import ApplicationInstanceFactory
from sandbox.experiences.tests.factories import application_under_review
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.organisations.grants import record_milestone_grants
from sandbox.organisations.models import MILESTONE_KEYCLOAK_ROLES
from sandbox.organisations.models import Milestone
from sandbox.organisations.models import MilestoneGrant
from sandbox.organisations.selectors import granted_milestones
from sandbox.organisations.selectors import unmet_prerequisites
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPROVAL = {
    "production_client_id": "PROD-CLIENT-1001",
    "certificate_reference": "CERT-2026-1001",
    "effective_date": None,
}


@pytest.fixture
def reviewer(db):
    return review_role_holder("decision_maker")


@pytest.fixture
def owner(db):
    return UserFactory(email="owner@vendor.in")


@pytest.fixture
def under_review(db, owner, reviewer):
    return application_under_review(owner, reviewer)


def _grant(organisation, milestone, application=None):
    return MilestoneGrant.objects.create(
        organisation=organisation,
        milestone=milestone,
        granted_by=application or ApplicationInstanceFactory(organisation=organisation),
    )


# ── The DAG ──────────────────────────────────────────────────────────────────


def test_m1_m2_and_m3_owe_nothing():
    """NHA states no ordering between them, so we enforce none."""
    organisation = ApplicationInstanceFactory().organisation

    for milestone in (Milestone.M1, Milestone.M2, Milestone.M3):
        assert unmet_prerequisites(organisation, milestone) == ()


def test_m4_owes_the_other_three():
    organisation = ApplicationInstanceFactory().organisation

    assert set(unmet_prerequisites(organisation, Milestone.M4)) == {
        Milestone.M1,
        Milestone.M2,
        Milestone.M3,
    }


def test_a_held_prerequisite_stops_being_owed():
    application = ApplicationInstanceFactory()
    _grant(application.organisation, Milestone.M1, application)

    assert set(unmet_prerequisites(application.organisation, Milestone.M4)) == {
        Milestone.M2,
        Milestone.M3,
    }


def test_prerequisites_granted_in_the_same_approval_count():
    """Approving M1 through M4 at once is legal; checking against stored grants
    alone would reject it."""
    organisation = ApplicationInstanceFactory().organisation

    assert (
        unmet_prerequisites(
            organisation,
            Milestone.M4,
            also_granting=[Milestone.M1, Milestone.M2, Milestone.M3],
        )
        == ()
    )


def test_every_milestone_owes_keycloak_roles():
    """§3.1: all four owe roles, so a grant needs no "none owed" state."""
    for milestone in Milestone.values:
        assert MILESTONE_KEYCLOAK_ROLES[milestone]


# ── Written by the reviewer's verification ───────────────────────────────────


def _declare(application, _owner, milestones):
    """The applicant's attestation, and the certification the verify gates on."""
    completed = timezone.localdate() - timedelta(days=30)
    data = {"milestones": list(milestones)}
    for milestone in milestones:
        data[f"{milestone}_completed_on"] = completed.isoformat()
    # `application_under_review` already made one per form; fill them in.
    ApplicationFormSubmission.objects.filter(
        application=application,
        form_key__in=("milestone_declaration", "security_certification"),
    ).update(status=SubmissionStatus.COMPLETED)
    application.submissions.filter(form_key="milestone_declaration").update(data=data)


def _verify(application, reviewer):
    return perform_form_action(
        application=application,
        form_key="milestone_declaration",
        action_key="verify_milestones",
        user=reviewer,
    )


def test_verification_grants_the_declared_milestones(
    under_review,
    owner,
    reviewer,
    django_capture_on_commit_callbacks,
):
    _declare(under_review, owner, ["m1", "m2"])

    with django_capture_on_commit_callbacks(execute=True):
        _verify(under_review, reviewer)

    assert granted_milestones(under_review.organisation) == {
        Milestone.M1,
        Milestone.M2,
    }


def test_declaring_alone_grants_nothing(under_review, owner):
    """It is an attestation. Nothing is earned until NHA has verified it."""
    _declare(under_review, owner, ["m1", "m2"])

    assert granted_milestones(under_review.organisation) == frozenset()


def test_the_grant_lands_only_after_the_verification_commits(
    under_review,
    owner,
    reviewer,
    django_capture_on_commit_callbacks,
):
    """A grant carries realm roles, so it must never follow a rolled-back
    verification."""
    _declare(under_review, owner, ["m1"])

    with django_capture_on_commit_callbacks(execute=True):
        _verify(under_review, reviewer)
        assert granted_milestones(under_review.organisation) == frozenset()

    assert granted_milestones(under_review.organisation) == {Milestone.M1}


def test_verification_needs_the_security_certification_first(under_review, reviewer):
    """WASA is bundled with the declaration: the audit backs the attestation."""
    under_review.submissions.filter(form_key="milestone_declaration").update(
        data={"milestones": ["m1"]},
        status=SubmissionStatus.COMPLETED,
    )
    under_review.submissions.filter(form_key="security_certification").update(
        status=SubmissionStatus.NEEDS_CHANGES,
    )
    context = application_context(under_review, reviewer)
    definition = registry.get(under_review.application_type)
    action = definition.get_form("milestone_declaration").actions[0]
    submission = under_review.submissions.get(form_key="milestone_declaration")

    available, reason = action.availability(context, submission)

    assert available is False
    assert "security certification" in str(reason)


def test_an_applicant_cannot_verify_their_own_declaration(under_review, owner):
    _declare(under_review, owner, ["m1"])

    with pytest.raises(PermissionDenied):
        _verify(under_review, owner)

    assert granted_milestones(under_review.organisation) == frozenset()


def test_a_grant_outlives_the_application_that_made_it(
    under_review,
    owner,
    reviewer,
    django_capture_on_commit_callbacks,
):
    """The reason it is organisation-scoped: a later application reads these
    rather than re-deriving from forms."""
    _declare(under_review, owner, ["m1"])
    with django_capture_on_commit_callbacks(execute=True):
        _verify(under_review, reviewer)

    later = ApplicationInstanceFactory(organisation=under_review.organisation)

    assert Milestone.M1 in granted_milestones(later.organisation)


def test_one_grant_per_organisation_and_milestone():
    application = ApplicationInstanceFactory()
    _grant(application.organisation, Milestone.M1, application)

    with pytest.raises(Exception, match="unique"):
        _grant(application.organisation, Milestone.M1, application)


def test_re_verifying_does_not_move_an_earlier_grant(under_review):
    """Grants are additive. `granted_at` records when it was first earned."""
    record_milestone_grants(under_review, ["m1"])
    first = MilestoneGrant.objects.get(milestone="m1").granted_at

    record_milestone_grants(under_review, ["m1", "m2"])

    assert MilestoneGrant.objects.get(milestone="m1").granted_at == first
    assert granted_milestones(under_review.organisation) == {
        Milestone.M1,
        Milestone.M2,
    }


def test_roles_are_unattached_until_provisioning_says_otherwise():
    application = ApplicationInstanceFactory()
    grant = _grant(application.organisation, Milestone.M2, application)

    assert grant.roles_attached == []
    assert grant.roles_attached_at is None
    assert grant.roles_owed == ("hip", "HIP_PAYER")


# ── The gate on the approval form ────────────────────────────────────────────


def _posted(milestones):
    return {
        **APPROVAL,
        "approved_milestones": milestones,
        "effective_date": "2026-09-07",
    }


def test_the_form_refuses_m4_without_its_prerequisites(under_review, reviewer):
    from sandbox.experiences.abdm.forms import ApprovalForm  # noqa: PLC0415
    from sandbox.experiences.services import application_context  # noqa: PLC0415

    form = ApprovalForm(
        data=_posted(["m4"]),
        experience_context=application_context(under_review, reviewer),
    )

    assert not form.is_valid()
    assert "M1" in str(form.errors["approved_milestones"])


def test_the_form_allows_m4_alongside_the_three_it_owes(under_review, reviewer):
    from sandbox.experiences.abdm.forms import ApprovalForm  # noqa: PLC0415
    from sandbox.experiences.services import application_context  # noqa: PLC0415

    form = ApprovalForm(
        data=_posted(["m1", "m2", "m3", "m4"]),
        experience_context=application_context(under_review, reviewer),
    )

    assert form.is_valid(), form.errors


def test_the_form_allows_m4_when_the_three_are_already_held(under_review, reviewer):
    from sandbox.experiences.abdm.forms import ApprovalForm  # noqa: PLC0415
    from sandbox.experiences.services import application_context  # noqa: PLC0415

    for milestone in (Milestone.M1, Milestone.M2, Milestone.M3):
        _grant(under_review.organisation, milestone, under_review)

    form = ApprovalForm(
        data=_posted(["m4"]),
        experience_context=application_context(under_review, reviewer),
    )

    assert form.is_valid(), form.errors
