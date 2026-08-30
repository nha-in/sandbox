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
from sandbox.workflow.services import register_hook

if TYPE_CHECKING:
    from collections.abc import Callable

    from sandbox.applications.models import Application
    from sandbox.workflow.models import WorkflowTransition

#: hook name (machine.py) -> the template it sends
HOOK_TEMPLATES: dict[str, TemplateKey] = {
    "notify_rejected": TemplateKey.SANDBOX_REJECTED,
    "notify_provisioned": TemplateKey.SANDBOX_APPROVED,
    "notify_production_approved": TemplateKey.PRODUCTION_APPROVED,
    "notify_exit_rejected": TemplateKey.EXIT_REJECTED,
    "notify_exit_sent_back": TemplateKey.EXIT_SENT_BACK,
}

#: templates that quote the reviewer back to the applicant
COMMENT_TEMPLATES = frozenset(
    {
        TemplateKey.SANDBOX_REJECTED,
        TemplateKey.EXIT_REJECTED,
        TemplateKey.EXIT_SENT_BACK,
    },
)


def _panel_url(application: Application) -> str:
    """Where the applicant collects credentials. C7's panel takes this route
    over once it lands; the setting is the seam.

    Named `panel_url` rather than `credentials_url` because `enqueue` refuses
    any params key containing "credential" — a blunt rule worth a rename.
    """
    path = reverse(
        settings.NOTIFICATION_CREDENTIALS_ROUTE,
        kwargs={"external_id": application.external_id},
    )
    return urljoin(settings.NOTIFICATION_PORTAL_BASE_URL, path)


def _decision_comment(
    application: Application,
    transition: WorkflowTransition,
) -> str:
    """A review-driven action leaves its text on the review row, not the
    transition (A6), so read whichever of the two actually has it."""
    if transition.comment:
        return transition.comment
    review = application.reviews.order_by("-decided_at").first()
    return review.comment if review else ""


def _params(
    template: TemplateKey,
    application: Application,
    transition: WorkflowTransition,
) -> dict[str, str]:
    params = {
        "reference": application.reference,
        "product": application.product.name,
        "applicant": application.applicant.name or application.applicant.email,
    }
    if template is TemplateKey.SANDBOX_APPROVED:
        params["panel_url"] = _panel_url(application)
    if template in COMMENT_TEMPLATES:
        params["comment"] = _decision_comment(application, transition)
    return params


def _handler(
    template: TemplateKey,
) -> Callable[[Application, WorkflowTransition], None]:
    def handle(application: Application, transition: WorkflowTransition) -> None:
        enqueue(
            template_key=template,
            recipient=application.applicant.email,
            params=_params(template, application, transition),
            application=application,
            user=application.applicant,
        )

    return handle


def register_workflow_hooks() -> None:
    """Called from `NotificationsConfig.ready()`."""
    for name, template in HOOK_TEMPLATES.items():
        register_hook(name, _handler(template))
