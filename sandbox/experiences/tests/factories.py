"""A bare `ApplicationInstance`, for tests that need a row rather than a workflow.

`create_application` is the real entry point and stays so — it checks
membership, grants the owner their access and writes the opening event. That is
what a test of the engine wants. It is not what a test of a database constraint
or an email body wants, and building one through the service means a
membership, an access grant and an event per row.

`reference` mirrors the service's own shape (`PREFIX-YY-XXXXXX`) but is a
sequence, not `secrets`: a factory that could collide would fail rarely and
inexplicably.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from factory import LazyAttribute
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from sandbox.experiences.models import ApplicationInstance
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

APPLICATION_TYPE = "abdm_production_access"


class ApplicationInstanceFactory(DjangoModelFactory[ApplicationInstance]):
    reference = Sequence(lambda n: f"ABDM-{timezone.now():%y}-{n:06d}")
    application_type = APPLICATION_TYPE
    title = "ABDM production access"
    organisation = SubFactory(OrganisationFactory, onboarded=True)
    created_by = SubFactory(UserFactory)
    status = "draft"

    class Meta:
        model = ApplicationInstance


class ApprovedApplicationFactory(ApplicationInstanceFactory):
    """Past the decision, which is where provisioning and its emails live."""

    status = "approved"
    decided_at = LazyAttribute(lambda _o: timezone.now())


def gate_data() -> dict[str, dict]:
    """The minimum §6 D1's exit gate accepts. Keyed by form."""
    from django.utils import timezone  # noqa: PLC0415

    today = timezone.localdate()
    return {
        "conformance_evidence": {
            "functional_testing_agency": "Empanelled Agency",
            "functional_certificate_number": "FT-2026-0001",
            "demonstration_date": today.isoformat(),
        },
        "security_certification": {
            "certification_type": "wasa",
            "expires_on": (today + timedelta(days=180)).isoformat(),
        },
        "technical_readiness": {
            "production_callback_url": "https://abdm.example.in/callback",
        },
    }


def review_role_holder(role_key: str = "decision_maker", *, email: str = ""):
    """An NHA actor, by standing role rather than per-application grant (§5)."""
    from sandbox.experiences.models import ReviewRole  # noqa: PLC0415
    from sandbox.experiences.models import ReviewRoleAssignment  # noqa: PLC0415

    user = UserFactory.create(email=email or f"{role_key}@nha.gov.in")
    ReviewRoleAssignment.objects.create(
        user=user,
        role=ReviewRole.objects.get(key=role_key),
    )
    return user


def application_under_review(owner, reviewer):
    """A real application, walked to `under_review` through the registry.

    Built by the service rather than the factory above, because the point of
    these callers is what an *action* causes — an application that never went
    through `submit` and `start_review` could not be approved at all.
    """
    from sandbox.experiences.models import ApplicationFormSubmission  # noqa: PLC0415
    from sandbox.experiences.registry import registry  # noqa: PLC0415
    from sandbox.experiences.services import create_application  # noqa: PLC0415
    from sandbox.experiences.services import perform_application_action  # noqa: PLC0415
    from sandbox.organisations.models import Membership  # noqa: PLC0415
    from sandbox.organisations.models import Role  # noqa: PLC0415

    organisation = OrganisationFactory(onboarded=True, name="Sunrise Health Systems")
    Membership.objects.create(organisation=organisation, user=owner, role=Role.OWNER)
    application = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
    )
    for form_definition in registry.get(APPLICATION_TYPE).forms:
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_definition.key,
            data=gate_data().get(form_definition.key, {}),
            submitted_by=owner,
        )
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
