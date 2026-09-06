"""What each lifecycle email says, and what it must never say.

The old version of this file tested `sandbox/workflow/`'s hook registry, which
no longer exists — notifications are `ActionResult.effects` now, and *that* a
decision sends its email is covered where the decision is made
(`integrations/tests/test_provisioning.py`). What is left here is the part
nothing else asserts: the body `_params` assembles.
"""

from __future__ import annotations

import pytest

from sandbox.experiences.models import ApplicationEvent
from sandbox.experiences.models import EventKind
from sandbox.experiences.tests.factories import ApprovedApplicationFactory
from sandbox.notifications.hooks import send
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey

pytestmark = pytest.mark.django_db

REVIEWER_NOTE = "The security assessment did not cover the gateway callback host."


@pytest.fixture
def application(db):
    return ApprovedApplicationFactory.create(
        organisation__name="Sunrise Health Systems",
        created_by__name="Meera Krishnan",
        created_by__email="meera@sunrise.in",
    )


def _decided(application, description: str) -> None:
    """The note a reviewer left, where the action leaves it — on the event."""
    ApplicationEvent.objects.create(
        application=application,
        kind=EventKind.STATUS_CHANGED,
        title="Application rejected",
        description=description,
        action_key="reject",
    )


def _params(application, template) -> dict:
    send(template, application)
    return Message.objects.get(
        application=application,
        template_key=template,
    ).params


def test_every_email_names_the_application_the_product_and_the_applicant(
    application,
):
    params = _params(application, TemplateKey.PRODUCTION_APPROVED)

    assert params["reference"] == application.reference
    assert params["product"] == "Sunrise Health Systems"
    assert params["applicant"] == "Meera Krishnan"


def test_the_applicant_falls_back_to_their_email_when_unnamed(application):
    application.created_by.name = ""
    application.created_by.save(update_fields=["name"])

    params = _params(application, TemplateKey.PRODUCTION_APPROVED)

    assert params["applicant"] == "meera@sunrise.in"


@pytest.mark.parametrize(
    "template",
    [
        TemplateKey.EXIT_REJECTED,
        TemplateKey.EXIT_SENT_BACK,
        TemplateKey.SANDBOX_REJECTED,
    ],
)
def test_a_decision_against_the_applicant_quotes_the_reviewer(application, template):
    """The note lives on the event the action wrote, so the hook goes and
    finds it. An applicant told only "rejected" has nothing to act on."""
    _decided(application, REVIEWER_NOTE)

    assert _params(application, template)["comment"] == REVIEWER_NOTE


def test_a_decision_with_no_note_still_sends(application):
    """Every action's note is optional, so an absent one is not an error."""
    _decided(application, "")

    assert _params(application, TemplateKey.EXIT_REJECTED)["comment"] == ""


def test_an_approval_quotes_nothing(application):
    """Only the three templates that carry bad news take a comment; an
    approval quoting the reviewer's internal note would leak it."""
    _decided(application, REVIEWER_NOTE)

    assert "comment" not in _params(application, TemplateKey.PRODUCTION_APPROVED)


def test_only_the_credentials_email_carries_the_panel_link(application, settings):
    settings.NOTIFICATION_PORTAL_BASE_URL = "https://portal.example.in"

    approved = _params(application, TemplateKey.SANDBOX_APPROVED)

    assert approved["panel_url"].startswith("https://portal.example.in/")
    assert application.reference in approved["panel_url"]
    assert "panel_url" not in _params(application, TemplateKey.PRODUCTION_APPROVED)


def test_the_link_is_named_panel_url_because_enqueue_refuses_credential_keys(
    application,
):
    """`enqueue` rejects any params key containing "credential" — a blunt rule,
    and the reason this field is not called `credentials_url`."""
    from sandbox.notifications.services import enqueue  # noqa: PLC0415
    from sandbox.utils.errors import DomainError  # noqa: PLC0415

    with pytest.raises(DomainError):
        enqueue(
            template_key=TemplateKey.SANDBOX_APPROVED,
            recipient="meera@sunrise.in",
            params={"credentials_url": "https://portal.example.in/x/"},
        )
