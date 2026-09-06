"""Milestone grants: what an approval leaves behind, and the one ordering."""

from __future__ import annotations

import pytest

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
def under_review(db, reviewer):
    return application_under_review(UserFactory(email="owner@vendor.in"), reviewer)


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


# ── Written from the declaration ─────────────────────────────────────────────


def test_grants_are_recorded_for_the_milestones_earned(under_review):
    record_milestone_grants(under_review, ["m1", "m2"])

    assert granted_milestones(under_review.organisation) == {
        Milestone.M1,
        Milestone.M2,
    }
    assert MilestoneGrant.objects.get(milestone="m1").granted_by == under_review


def test_an_unknown_milestone_is_ignored(under_review):
    record_milestone_grants(under_review, ["m1", "m9"])

    assert granted_milestones(under_review.organisation) == {Milestone.M1}


def test_a_grant_outlives_the_application_that_made_it(under_review):
    """The reason it is organisation-scoped: a later application reads these
    rather than re-deriving from forms."""
    record_milestone_grants(under_review, ["m1"])

    later = ApplicationInstanceFactory(organisation=under_review.organisation)

    assert Milestone.M1 in granted_milestones(later.organisation)


def test_one_grant_per_organisation_and_milestone():
    application = ApplicationInstanceFactory()
    _grant(application.organisation, Milestone.M1, application)

    with pytest.raises(Exception, match="unique"):
        _grant(application.organisation, Milestone.M1, application)


def test_re_recording_does_not_move_an_earlier_grant(under_review):
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
