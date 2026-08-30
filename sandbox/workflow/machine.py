"""The legal state graph, as data.

Legacy encoded this as magic status integers (0-5, 9-11) scattered through 384
native SQL strings, so no one could answer "what moves are legal from here?"
without reading the whole service. Here the graph is a dict: the console asks it
what buttons to show, and the tests iterate it to assert every legal *and every
illegal* pair.

Nothing in this module touches the database — importing it is free, which is
what lets `machine.py` stay the single source of truth for both.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field

from sandbox.applications.models import ApplicationState


class Action(enum.StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SEND_BACK = "SEND_BACK"
    WITHDRAW = "WITHDRAW"
    START_PROVISIONING = "START_PROVISIONING"
    COMPLETE_PROVISIONING = "COMPLETE_PROVISIONING"
    FAIL_PROVISIONING = "FAIL_PROVISIONING"
    RETRY_PROVISIONING = "RETRY_PROVISIONING"
    REQUEST_EXIT = "REQUEST_EXIT"
    START_EXIT_REVIEW = "START_EXIT_REVIEW"
    APPROVE_EXIT = "APPROVE_EXIT"
    REJECT_EXIT = "REJECT_EXIT"
    SEND_BACK_EXIT = "SEND_BACK_EXIT"


class ActorKind(enum.StrEnum):
    """Who may perform a move.

    `SYSTEM` moves are the chain's own bookkeeping and must carry no user;
    `OWNER` moves belong to the applicant's organisation; `STAFF` moves need a
    Django permission. Keeping these apart is what stops a console permission
    accidentally granting a background job's transition, and vice versa.
    """

    OWNER = "OWNER"
    STAFF = "STAFF"
    SYSTEM = "SYSTEM"


# Permissions live on WorkflowTransition (see models.py). Authority is a
# permission check, never a username string — the legacy system matched "HTC1".
PERM_APPROVE = "workflow.approve_application"
PERM_REJECT = "workflow.reject_application"
#: recording an opinion only — deliberately grants no transition
PERM_REVIEW = "workflow.review_application"
PERM_SEND_BACK = "workflow.send_back_application"
PERM_RETRY_PROVISIONING = "workflow.retry_provisioning"


@dataclass(frozen=True, slots=True)
class Spec:
    to_state: ApplicationState
    actor_kind: ActorKind
    permission: str = ""
    #: names resolved against the hook registry at commit time (B7/B8 register)
    hooks: tuple[str, ...] = field(default_factory=tuple)
    #: names resolved against the guard registry, run *before* the move and
    #: able to refuse it. Kept on the table so a console calling `transition()`
    #: generically cannot route around them.
    guards: tuple[str, ...] = field(default_factory=tuple)
    #: `DeclarationState` value to settle the pending exit declaration to.
    #: A plain string because this module must not import another app.
    settles_declaration: str = ""
    #: A6 records this decision's text on the review row, so the transition
    #: must not carry a comment too (03-database.md: "single home for the text").
    review_driven: bool = False


S = ApplicationState

TRANSITIONS: dict[tuple[ApplicationState, Action], Spec] = {
    # Apply
    (S.DRAFT, Action.SUBMIT): Spec(S.SUBMITTED, ActorKind.OWNER),
    (S.SENT_BACK, Action.SUBMIT): Spec(S.SUBMITTED, ActorKind.OWNER),
    (S.DRAFT, Action.WITHDRAW): Spec(S.WITHDRAWN, ActorKind.OWNER),
    (S.SUBMITTED, Action.WITHDRAW): Spec(S.WITHDRAWN, ActorKind.OWNER),
    (S.SENT_BACK, Action.WITHDRAW): Spec(S.WITHDRAWN, ActorKind.OWNER),
    # Review
    (S.SUBMITTED, Action.APPROVE): Spec(
        S.SANDBOX_APPROVED,
        ActorKind.STAFF,
        PERM_APPROVE,
        hooks=("provisioning_chain",),
        review_driven=True,
    ),
    (S.SUBMITTED, Action.REJECT): Spec(
        S.REJECTED,
        ActorKind.STAFF,
        PERM_REJECT,
        hooks=("deprovisioning_chain", "notify_rejected"),
        review_driven=True,
    ),
    (S.SUBMITTED, Action.SEND_BACK): Spec(
        S.SENT_BACK,
        ActorKind.STAFF,
        PERM_SEND_BACK,
        review_driven=True,
    ),
    # Provisioning (B7). The chain owns these; a person never drives them.
    (S.SANDBOX_APPROVED, Action.START_PROVISIONING): Spec(
        S.PROVISIONING,
        ActorKind.SYSTEM,
    ),
    (S.PROVISIONING, Action.COMPLETE_PROVISIONING): Spec(
        S.PROVISIONED,
        ActorKind.SYSTEM,
        hooks=("notify_provisioned",),
    ),
    (S.PROVISIONING, Action.FAIL_PROVISIONING): Spec(
        S.PROVISIONING_FAILED,
        ActorKind.SYSTEM,
        hooks=("alert_provisioning_failed",),
    ),
    (S.PROVISIONING_FAILED, Action.RETRY_PROVISIONING): Spec(
        S.PROVISIONING,
        ActorKind.STAFF,
        PERM_RETRY_PROVISIONING,
        hooks=("provisioning_chain",),
    ),
    # Withdrawal after provisioning strands ACTIVE ledger rows, so it is the
    # v0 path that triggers deprovisioning (B8 documents the covered set).
    (S.PROVISIONED, Action.WITHDRAW): Spec(
        S.WITHDRAWN,
        ActorKind.OWNER,
        hooks=("deprovisioning_chain",),
    ),
    # Exit. Provisional until open question 3 is answered — if exits turn out to
    # be per-milestone-track and repeatable, A8 replaces these edges with a
    # scoped record rather than terminal application states.
    (S.PROVISIONED, Action.REQUEST_EXIT): Spec(
        S.EXIT_REQUESTED,
        ActorKind.OWNER,
        guards=("exit_bundle",),
    ),
    (S.EXIT_REJECTED, Action.REQUEST_EXIT): Spec(
        S.EXIT_REQUESTED,
        ActorKind.OWNER,
        guards=("exit_bundle",),
    ),
    (S.EXIT_REQUESTED, Action.START_EXIT_REVIEW): Spec(
        S.EXIT_REVIEW,
        ActorKind.STAFF,
        PERM_APPROVE,
    ),
    (S.EXIT_REVIEW, Action.APPROVE_EXIT): Spec(
        S.PRODUCTION_APPROVED,
        ActorKind.STAFF,
        PERM_APPROVE,
        hooks=("notify_production_approved",),
        settles_declaration="APPROVED",
        review_driven=True,
    ),
    (S.EXIT_REVIEW, Action.REJECT_EXIT): Spec(
        S.EXIT_REJECTED,
        ActorKind.STAFF,
        PERM_REJECT,
        hooks=("notify_exit_rejected",),
        settles_declaration="REJECTED",
        review_driven=True,
    ),
    # Send-back settles the bundle too: leaving it SUBMITTED would make the
    # column ambiguous between "awaiting review" and "bounced back".
    (S.EXIT_REVIEW, Action.SEND_BACK_EXIT): Spec(
        S.PROVISIONED,
        ActorKind.STAFF,
        PERM_SEND_BACK,
        hooks=("notify_exit_sent_back",),
        settles_declaration="REJECTED",
        review_driven=True,
    ),
}

#: every (from_state, action, to_state) the CHECK constraint will accept
LEGAL_EDGES: frozenset[tuple[str, str, str]] = frozenset(
    (from_state, action, spec.to_state)
    for (from_state, action), spec in TRANSITIONS.items()
)

TERMINAL_STATES = frozenset(
    {S.REJECTED, S.WITHDRAWN, S.PRODUCTION_APPROVED},
)


def actions_available(state: ApplicationState | str) -> tuple[Action, ...]:
    """What the console may offer from `state`, before permission filtering."""
    return tuple(action for (from_state, action) in TRANSITIONS if from_state == state)
