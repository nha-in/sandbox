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

SANDBOX_ACCESS_TYPE = "abdm_sandbox_access"
MILESTONE_EXIT_TYPE = "abdm_milestone_exit"

#: What most callers mean: the exit is where review, evidence and approval live.
APPLICATION_TYPE = MILESTONE_EXIT_TYPE


class ApplicationInstanceFactory(DjangoModelFactory[ApplicationInstance]):
    reference = Sequence(lambda n: f"ABDM-{timezone.now():%y}-{n:06d}")
    application_type = APPLICATION_TYPE
    title = "ABDM milestone exit"
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
        "milestone_declaration": {
            "milestones": ["m1"],
            "m1_completed_on": today.isoformat(),
            "demonstrated_on_current_apis": True,
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


def provisioned_sandbox_access(owner, organisation):
    """An approved sandbox access holding a live client (plan 12 §1.2).

    Built directly rather than walked through its own gate: `can_start` only
    asks whether one exists, and walking the first gate for every exit fixture
    would triple what each of these tests costs.
    """
    from sandbox.integrations.models import ProvisionedResource  # noqa: PLC0415
    from sandbox.integrations.models import ProvisionedResourceState  # noqa: PLC0415
    from sandbox.integrations.models import ProvisionedSystem  # noqa: PLC0415

    application = ApplicationInstanceFactory(
        application_type=SANDBOX_ACCESS_TYPE,
        title="ABDM sandbox access",
        organisation=organisation,
        created_by=owner,
        status="approved",
    )
    ProvisionedResource.objects.create(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
        external_ref="keycloak-test-client",
        public_ref="SBX-TEST-0001",
        state=ProvisionedResourceState.ACTIVE,
    )
    return application


def sandbox_access_under_review(owner, reviewer):
    """The first gate, walked to `under_review` — one action from provisioning.

    Its own walk rather than `provisioned_sandbox_access`, because the callers
    here are testing what *approval* sets running.
    """
    from sandbox.experiences.models import ApplicationFormSubmission  # noqa: PLC0415
    from sandbox.experiences.registry import registry  # noqa: PLC0415
    from sandbox.experiences.services import create_application  # noqa: PLC0415
    from sandbox.experiences.services import perform_application_action  # noqa: PLC0415
    from sandbox.organisations.models import Membership  # noqa: PLC0415
    from sandbox.organisations.models import Role  # noqa: PLC0415

    organisation = OrganisationFactory(onboarded=True, name="Sunrise Health Systems")
    Membership.objects.get_or_create(
        organisation=organisation,
        user=owner,
        defaults={"role": Role.OWNER},
    )
    application = create_application(
        application_type=SANDBOX_ACCESS_TYPE,
        organisation=organisation,
        user=owner,
    )
    for form_definition in registry.get(SANDBOX_ACCESS_TYPE).forms:
        if not form_definition.required:
            continue
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_definition.key,
            data={},
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


def application_under_review(owner, reviewer):
    """A milestone exit walked to `under_review` through the registry.

    Built by the service rather than the factory above, because the point of
    these callers is what an *action* causes — an application that never went
    through `submit` and `start_review` could not be approved at all. The
    sandbox access it is filed against comes first: `can_start` refuses an exit
    without one.
    """
    from sandbox.experiences.models import ApplicationFormSubmission  # noqa: PLC0415
    from sandbox.experiences.registry import registry  # noqa: PLC0415
    from sandbox.experiences.services import create_application  # noqa: PLC0415
    from sandbox.experiences.services import perform_application_action  # noqa: PLC0415
    from sandbox.organisations.models import Membership  # noqa: PLC0415
    from sandbox.organisations.models import Role  # noqa: PLC0415

    organisation = OrganisationFactory(onboarded=True, name="Sunrise Health Systems")
    Membership.objects.create(organisation=organisation, user=owner, role=Role.OWNER)
    sandbox_access = provisioned_sandbox_access(owner, organisation)
    application = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner,
        predecessor=sandbox_access,
    )
    answers = gate_data()
    for form_definition in registry.get(APPLICATION_TYPE).forms:
        if not form_definition.required:
            continue
        ApplicationFormSubmission.objects.create(
            application=application,
            form_key=form_definition.key,
            data=answers.get(form_definition.key, {}),
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
