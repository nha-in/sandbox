"""Resolving the sandbox access a milestone exit was filed against (§1.2).

An exit is its own application, so anything it needs from the registration —
the roles the integrator declared, the credentials in play — is reached through
the reference its first form records, not by reading a sibling's forms blindly.
"""

from __future__ import annotations

from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.models import ApplicationInstance
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem

SANDBOX_ACCESS_TYPE = "abdm_sandbox_access"


def provisioned_sandbox_accesses(organisation):
    """Approved sandbox accesses that actually hold a client, newest first.

    Approval alone is not enough: the chain can fail after it, and an exit
    filed against credentials that were never issued has nothing to describe.
    """
    with_client = ProvisionedResource.objects.filter(
        system=ProvisionedSystem.KEYCLOAK,
        state=ProvisionedResourceState.ACTIVE,
    ).values("application_id")
    return (
        ApplicationInstance.objects.filter(
            organisation=organisation,
            application_type=SANDBOX_ACCESS_TYPE,
            status="approved",
            pk__in=with_client,
        )
        .select_related("product")
        .order_by("-decided_at", "-pk")
    )


def referenced_sandbox_access(context) -> ApplicationInstance | None:
    """The sandbox access this exit was opened from.

    Recorded at creation from the URL the applicant navigated by, so it is
    present from the first moment and never editable.
    """
    reference = (context.application.metadata or {}).get("predecessor")
    if not reference:
        return None
    return ApplicationInstance.objects.filter(
        organisation=context.application.organisation,
        application_type=SANDBOX_ACCESS_TYPE,
        reference=reference,
    ).first()


def sandbox_access_form_data(context, form_key: str) -> dict:
    """One of the referenced application's submissions, or an empty dict.

    Empty rather than raising: the exit's own forms are filled in order, so
    every caller has to cope with the reference not being there yet.
    """
    application = referenced_sandbox_access(context)
    if application is None:
        return {}
    submission = ApplicationFormSubmission.objects.filter(
        application=application,
        form_key=form_key,
    ).first()
    return submission.data if submission else {}


MILESTONE_EXIT_TYPE = "abdm_milestone_exit"


def follow_on_definitions(application):
    """Types that may be started from *this* application.

    Only a sandbox access with live credentials leads anywhere: an exit is
    about credentials, so there is nothing to file against one that has none.
    """
    from sandbox.experiences.registry import registry  # noqa: PLC0415

    if application.application_type != SANDBOX_ACCESS_TYPE:
        return []
    if (
        not provisioned_sandbox_accesses(application.organisation)
        .filter(
            pk=application.pk,
        )
        .exists()
    ):
        return []
    return [registry.get(MILESTONE_EXIT_TYPE)]


def follow_on_applications(application):
    """Everything filed against this application, newest first."""
    if application.application_type != SANDBOX_ACCESS_TYPE:
        return []
    return list(
        ApplicationInstance.objects.filter(
            organisation=application.organisation,
            metadata__predecessor=application.reference,
        ).order_by("-created_at", "-pk"),
    )


def predecessor_of(application) -> ApplicationInstance | None:
    """The application this one was opened from, if any."""
    reference = (application.metadata or {}).get("predecessor")
    if not reference:
        return None
    return ApplicationInstance.objects.filter(
        organisation=application.organisation,
        reference=reference,
    ).first()
