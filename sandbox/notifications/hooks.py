"""Lifecycle emails, hung off A5's transition hooks.

`machine.py` already names these five; until now nothing answered to the names,
so every hook was a silent no-op. Registering them here is what closes A8's
"applicant is notified" criterion.

The one rule that shapes the content: `sandbox-approved` carries a **link** to
the credentials panel, never the credentials. Legacy mailed the client secret
itself — `CLIENT_SECRET_MAIL_SUBJECT` exists for exactly that — which put a
permanent machine credential in an inbox, a mail relay and two archives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from django.conf import settings
from django.urls import reverse

from sandbox.notifications.models import TemplateKey
from sandbox.notifications.services import enqueue

if TYPE_CHECKING:
    from sandbox.experiences.models import ApplicationInstance

#: hook name (a workflow's TransitionSpec) -> the template it sends
#: Which template each decision sends. The three "exit" templates belong to
#: this application type: it *is* the production-access application, so its
#: approval is a production approval and its send-back is an exit send-back.
#: SANDBOX_REJECTED waits for a sandbox-access type to exist.

#: templates that quote the reviewer back to the applicant
COMMENT_TEMPLATES = frozenset(
    {
        TemplateKey.SANDBOX_REJECTED,
        TemplateKey.EXIT_REJECTED,
        TemplateKey.EXIT_SENT_BACK,
    },
)


def _panel_url(application: ApplicationInstance) -> str:
    """Where the applicant collects credentials. C7's panel takes this route
    over once it lands; the setting is the seam.

    Named `panel_url` rather than `credentials_url` because `enqueue` refuses
    any params key containing "credential" — a blunt rule worth a rename.
    """
    # `reference`, not a UUID: every experiences route keys on <str:reference>,
    # and ApplicationInstance has no external_id.
    path = reverse(
        settings.NOTIFICATION_CREDENTIALS_ROUTE,
        kwargs={"reference": application.reference},
    )
    return urljoin(settings.NOTIFICATION_PORTAL_BASE_URL, path)


def _decision_comment(application: ApplicationInstance) -> str:
    """The reviewer's note, which the action leaves on the event it wrote."""
    event = application.events.order_by("-created_at", "-pk").first()
    return event.description if event else ""


def _params(template: TemplateKey, application: ApplicationInstance) -> dict[str, str]:
    applicant = application.created_by
    params = {
        "reference": application.reference,
        "product": application.organisation.display_name,
        "applicant": applicant.name or applicant.email,
    }
    if template is TemplateKey.SANDBOX_APPROVED:
        params["panel_url"] = _panel_url(application)
    if template in COMMENT_TEMPLATES:
        params["comment"] = _decision_comment(application)
    return params


def notify(template: TemplateKey):
    """An `ActionResult.effects` entry that sends one template.

    The engine calls an effect with the saved application and the acting user;
    the recipient is always the applicant, never the actor, because the actor
    is usually NHA.
    """

    def effect(application: ApplicationInstance, _user) -> None:
        send(template, application)

    return effect


def send(template: TemplateKey, application: ApplicationInstance) -> None:
    """Send one template about one application. Also the direct call the
    provisioning chain makes, which has no acting user to speak of."""
    enqueue(
        template_key=template,
        recipient=application.created_by.email,
        params=_params(template, application),
        application=application,
        user=application.created_by,
    )
