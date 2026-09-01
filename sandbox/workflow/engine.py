"""The engine: the only two write paths for workflow data.

`submit_form()` is the only code that inserts an `ApplicationFormSubmission`;
`transition()` is the only code that writes `Application.state` (and `round`).
Everything downstream — console buttons, the provisioning chain, the exit
flow — routes through here, so an application can never move off the books.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db import transaction

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationFormSubmission
from sandbox.audit.services import emit
from sandbox.utils.errors import DomainError
from sandbox.workflow.definitions import ActorKind
from sandbox.workflow.models import WorkflowTransition
from sandbox.workflow.registry import get_workflow

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

    from sandbox.users.models import User
    from sandbox.workflow.definitions import FormDefinition
    from sandbox.workflow.definitions import TransitionSpec


class ApplicationContext:
    """DB-backed `definitions.Context`: current submissions in one query."""

    def __init__(self, application: Application) -> None:
        self.application = application
        self._current: dict[str, ApplicationFormSubmission] = {
            submission.form_key: submission
            for submission in application.submissions.filter(is_current=True)
        }

    def has_current(self, form_key: str) -> bool:
        return form_key in self._current

    def has_current_at_round(self, form_key: str) -> bool:
        submission = self._current.get(form_key)
        return submission is not None and submission.round == self.application.round

    def form_data(self, form_key: str) -> Mapping[str, Any]:
        submission = self._current.get(form_key)
        return dict(submission.data) if submission else {}

    def current(self, form_key: str) -> ApplicationFormSubmission | None:
        return self._current.get(form_key)

    def product_has_current(self, workflow_key: str, form_key: str) -> bool:
        return ApplicationFormSubmission.objects.filter(
            application__product_id=self.application.product_id,
            application__workflow_key=workflow_key,
            application__deleted=False,
            form_key=form_key,
            is_current=True,
        ).exists()


#: hook name -> callable(application, transition). Integrations register theirs
#: at app-ready time; an unregistered name is a no-op so slices can ship apart.
_HOOKS: dict[str, Callable[[Application, WorkflowTransition], None]] = {}

#: guard name -> callable(application, context). Guards run before the move and
#: refuse it by raising; separate from hooks because a hook reacts to a move
#: that already happened, a guard can stop one.
_GUARDS: dict[str, Callable[[Application, ApplicationContext], None]] = {}


def register_hook(
    name: str,
    handler: Callable[[Application, WorkflowTransition], None],
) -> None:
    _HOOKS[name] = handler


def register_guard(
    name: str,
    handler: Callable[[Application, ApplicationContext], None],
) -> None:
    _GUARDS[name] = handler


def clear_hooks() -> None:
    """For tests that assert a chain fires exactly once — hooks only.

    Deliberately not `clear_registries`: dropping the guards with them would
    leave every gate open, which is the opposite of what a test wants.
    """
    _HOOKS.clear()


def clear_registries() -> None:
    """For tests — never call this from application code."""
    _HOOKS.clear()
    _GUARDS.clear()


def _check_guard(
    guard_name: str,
    application: Application,
    context: ApplicationContext,
    action: str,
) -> None:
    handler = _GUARDS.get(guard_name)
    if handler is None:
        # Fail closed: an unregistered guard must not silently permit the move.
        message = f"{action} requires guard {guard_name}, which is not registered"
        raise DomainError(message, code="guard_unavailable")
    handler(application, context)


def _check_actor(spec_kind: ActorKind, actor: User | None, action: str) -> None:
    if spec_kind is ActorKind.SYSTEM:
        if actor is not None:
            message = f"{action} is a system move and cannot carry an actor"
            raise DomainError(message, code="forbidden")
        return
    if actor is None:
        message = f"{action} requires an actor"
        raise DomainError(message, code="forbidden")


def _check_owner(application: Application, actor: User) -> None:
    """Owner moves belong to the applicant's organisation, not to any member."""
    organisation_id = application.product.organisation_id
    is_member = actor.memberships.filter(organisation_id=organisation_id).exists()
    if not is_member:
        message = "actor is not a member of the owning organisation"
        raise DomainError(message, code="forbidden")


def _carry_documents_forward(
    previous: ApplicationFormSubmission,
    submission: ApplicationFormSubmission,
) -> None:
    """Copy evidence onto the new revision; the old one keeps its own.

    A send-back typo fix must not force re-uploading the certificate, but the
    revision a reviewer judged has to keep the evidence they judged it on.
    Moving the rows satisfied the first and broke the second: every superseded
    revision ended up showing none.

    The copies share `storage_key`, so this is a row per revision, not a file
    per revision. A reviewer flag for a repeated `sha256` must therefore ignore
    carried copies, or every send-back would raise one.
    """
    ApplicationDocument.objects.bulk_create(
        [
            ApplicationDocument(
                submission=submission,
                kind=document.kind,
                storage_key=document.storage_key,
                filename=document.filename,
                content_type=document.content_type,
                size=document.size,
                sha256=document.sha256,
                uploaded_by=document.uploaded_by,
            )
            for document in previous.documents.filter(deleted=False)
        ],
    )


def _write_submission(
    locked: Application,
    definition: type[FormDefinition],
    cleaned_data: dict[str, Any],
    user: User,
) -> ApplicationFormSubmission:
    """Insert a revision; supersede and carry documents forward if superseding."""
    previous = None
    if not definition.repeatable:
        previous = (
            ApplicationFormSubmission.objects.select_for_update()
            .filter(application=locked, form_key=definition.key, is_current=True)
            .first()
        )
        if previous is not None:
            previous.is_current = False
            previous.save(update_fields=["is_current"])

    submission = ApplicationFormSubmission.objects.create(
        application=locked,
        form_key=definition.key,
        round=locked.round,
        data=cleaned_data,
        schema_version=definition.schema_version,
        # repeatable forms are pure history: nothing is ever "current"
        is_current=not definition.repeatable,
        submitted_by=user,
    )
    if previous is not None:
        _carry_documents_forward(previous, submission)
    return submission


@transaction.atomic
def submit_form(
    *,
    application: Application,
    form_key: str,
    cleaned_data: dict[str, Any],
    user: User,
) -> ApplicationFormSubmission:
    """Insert a new current revision of `form_key`; supersede the previous.

    Refuses unless the application's state is in the form's `editable_states`,
    the actor is a member of the owning organisation, and every `depends_on`
    form has a current submission. STAFF forms are refused outright — the
    engine writes those itself inside their deciding transition.
    """
    locked = Application.objects.select_for_update().get(pk=application.pk)
    workflow = get_workflow(locked.workflow_key)
    definition = workflow.form(form_key)

    if definition.actor_kind is ActorKind.STAFF:
        message = f"{form_key} is written by the engine inside its transition"
        raise DomainError(message, code="forbidden")

    _check_owner(locked, user)

    if locked.state not in definition.editable_states:
        message = f"{form_key} is not editable in state {locked.state}"
        raise DomainError(message, code="not_editable")

    context = ApplicationContext(locked)
    if not definition.is_unlocked(context):
        missing = [key for key in definition.depends_on if not context.has_current(key)]
        message = f"{form_key} requires {', '.join(missing)} first"
        raise DomainError(message, code="locked")

    submission = _write_submission(locked, definition, cleaned_data, user)

    emit(
        "application.form_submitted",
        obj=locked,
        actor=user,
        data={
            "form_key": form_key,
            "round": locked.round,
            "reference": locked.reference,
        },
    )
    return submission


def _check_authority(
    spec: TransitionSpec,
    locked: Application,
    actor: User | None,
    action: str,
    comment: str,
) -> None:
    _check_actor(spec.actor_kind, actor, action)

    if spec.actor_kind is ActorKind.OWNER and actor is not None:
        _check_owner(locked, actor)

    if spec.permission and (actor is None or not actor.has_perm(spec.permission)):
        message = f"{action} requires {spec.permission}"
        raise DomainError(message, code="forbidden")

    if spec.review_driven and comment:
        message = (
            f"{action} is review-driven; its comment belongs on the review row, "
            "not on the transition"
        )
        raise DomainError(message, code="comment_not_allowed")


def _write_decision(
    spec: TransitionSpec,
    locked: Application,
    actor: User | None,
    action: str,
    decision_data: dict[str, Any] | None,
) -> None:
    if not spec.decision_form_key:
        if decision_data is not None:
            message = f"{action} does not take a decision"
            raise DomainError(message, code="invalid")
        return
    if decision_data is None:
        message = f"{action} requires the {spec.decision_form_key} decision"
        raise DomainError(message, code="decision_required")
    if actor is None:
        message = f"{action} requires an actor to sign the decision"
        raise DomainError(message, code="forbidden")
    workflow = get_workflow(locked.workflow_key)
    definition = workflow.form(spec.decision_form_key)
    _write_submission(locked, definition, decision_data, actor)


@transaction.atomic
def transition(  # noqa: PLR0913 — the write path names every input explicitly
    *,
    application: Application,
    action: str,
    actor: User | None = None,
    comment: str = "",
    data: dict[str, Any] | None = None,
    decision_data: dict[str, Any] | None = None,
) -> WorkflowTransition:
    """Move `application` by `action`, atomically and audibly.

    `comment` is only for moves with no review behind them (withdrawal, system
    notes); a review-driven action's text is single-homed on the review row.
    Deciding transitions take the decision form's cleaned data and write the
    STAFF submission themselves, same transaction — the decision and the move
    cannot exist without each other. Side-effect hooks run only after commit.
    """
    # Locked re-read: two reviewers clicking Approve must not both succeed.
    locked = Application.objects.select_for_update().get(pk=application.pk)
    workflow = get_workflow(locked.workflow_key)
    from_state = locked.state

    spec: TransitionSpec | None = workflow.transitions.get((from_state, action))
    if spec is None:
        message = f"{action} is not legal from {from_state}"
        raise DomainError(message, code="illegal_transition")

    _check_authority(spec, locked, actor, action, comment)

    context = ApplicationContext(locked)
    for guard_name in spec.guards:
        _check_guard(guard_name, locked, context, action)

    _write_decision(spec, locked, actor, action, decision_data)

    record = WorkflowTransition.objects.create(
        application=locked,
        from_state=from_state,
        to_state=spec.to_state,
        action=action,
        actor=actor,
        comment=comment,
    )

    locked.state = spec.to_state
    update_fields = ["state", "modified_date"]
    if spec.advances_round:
        locked.round += 1
        update_fields.append("round")
    locked.save(update_fields=update_fields)
    application.state = locked.state
    application.round = locked.round

    emit(
        f"application.{action.lower()}",
        obj=locked,
        actor=actor,
        data={
            "from_state": from_state,
            "to_state": spec.to_state,
            "reference": locked.reference,
            **(data or {}),
        },
    )

    for hook_name in spec.hooks:
        handler = _HOOKS.get(hook_name)
        if handler is not None:
            transaction.on_commit(
                lambda handler=handler: handler(locked, record),  # type: ignore[misc]
            )

    return record
