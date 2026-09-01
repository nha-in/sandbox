"""The default guards, adapting programme predicates to the engine's registry.

A guard refuses a transition by raising `DomainError`. These are registered at
app-ready time; integrations register their own (evidence gating, P3) the same
way. The engine fails closed on unregistered names.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from django.utils import timezone

from sandbox.programmes import abdm
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from sandbox.applications.models import Application
    from sandbox.workflow.engine import ApplicationContext


def registration_complete(
    application: Application,
    context: ApplicationContext,
) -> None:
    """A draft may be incomplete; submitting it is when it must not be."""
    if not context.has_current("REGISTRATION"):
        message = "complete the registration form before submitting"
        raise DomainError(message, code="registration_incomplete")


def exit_gate(application: Application, context: ApplicationContext) -> None:
    """You may only exit milestones you have declared, with a current WASA."""
    covers = context.form_data("EXIT_CLAIM").get("covers", [])
    if not covers:
        message = "submit an exit declaration before requesting exit"
        raise DomainError(message, code="no_exit_claim")

    undeclared = [
        str(milestone)
        for milestone in covers
        if not context.product_has_current(
            "ABDM",
            abdm.milestone_form_key(milestone),
        )
    ]
    if undeclared:
        keys = ", ".join(undeclared)
        message = f"declare {keys} complete before exiting them to production"
        raise DomainError(message, code="milestone_not_declared")

    _require_wasa(context)
    _require_documents(context, "EXIT_CLAIM")
    _require_documents(context, "WASA")


def _require_wasa(context: ApplicationContext) -> None:
    """Validity is the real rule; the round only asks who still stands behind it.

    A statement that has not expired is safe to reuse across a send-back, so
    the applicant reaffirms it rather than re-uploading the certificate.
    """
    submission = context.current("WASA")
    if submission is None:
        message = "submit a Safe-to-Host statement before requesting exit"
        raise DomainError(message, code="wasa_missing")

    valid_upto = date.fromisoformat(str(submission.data["valid_upto"]))
    if valid_upto < timezone.localdate():
        message = (
            f"the Safe-to-Host statement expired on {valid_upto:%d %b %Y}; "
            f"attach a current one"
        )
        raise DomainError(message, code="wasa_expired")

    if submission.round != context.application.round:
        message = "confirm the Safe-to-Host statement still stands before resubmitting"
        raise DomainError(message, code="wasa_unconfirmed")


def _require_documents(context: ApplicationContext, form_key: str) -> None:
    submission = context.current(form_key)
    if submission is None:
        return
    workflow = abdm.ABDMExitWorkflow
    required = set(workflow.form(form_key).requires_document)
    attached = set(
        submission.documents.filter(deleted=False).values_list("kind", flat=True),
    )
    missing = sorted(required - attached)
    if missing:
        kinds = ", ".join(missing)
        message = f"{form_key} needs the following evidence: {kinds}"
        raise DomainError(message, code="documents_missing")


def register_default_guards() -> None:
    # Deferred: the engine imports models, which need the app registry ready.
    from sandbox.workflow import engine  # noqa: PLC0415

    engine.register_guard(abdm.GUARD_REGISTRATION_COMPLETE, registration_complete)
    engine.register_guard(abdm.GUARD_EXIT_GATE, exit_gate)
