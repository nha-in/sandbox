"""Workflow definitions: the base classes every programme builds from.

This module is the code half of the one rule in plan/09-redesign.md §2 —
which workflows exist, their states, their transitions and their forms are
declared here and in `sandbox.programmes`, never in the database. It imports
no models and touches no database, so importing it is free: the console, the
engine and the tests all read the same source of truth.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from django import forms


class ActorKind(enum.StrEnum):
    """Who may perform a move or submit a form.

    `SYSTEM` moves are the provisioning chain's own bookkeeping and must carry
    no user; `OWNER` moves belong to the applicant's organisation; `STAFF`
    moves need a Django permission. Keeping these apart is what stops a console
    permission accidentally granting a background job's transition.
    """

    OWNER = "OWNER"
    STAFF = "STAFF"
    SYSTEM = "SYSTEM"


# Authority is a permission check, never a username string — the legacy system
# matched "HTC1". Permissions are per programme, not global: the team reviewing
# ABDM must not thereby be able to decide an HCX application. Each programme
# module owns its own names and their labels; `Workflow.permissions` is what
# creates them at migrate time and what the registry-sanity test proves exist,
# so a name nobody created cannot become an invisible lockout.
#
# Names follow `workflow.<action>_<programme>`, e.g. `workflow.approve_abdm`.
PERM_RETRY_PROVISIONING = "workflow.retry_provisioning"


class Context(Protocol):
    """Read-only bundle handed to every predicate and guard.

    Implementations prefetch the application's current submissions in one
    query; `product_has_current` is the single cross-application read, which
    is what lets a programme reuse a sibling programme's claims (HCX accepting
    the product's ABDM M1) by explicit code opt-in.
    """

    def has_current(self, form_key: str) -> bool:
        """True if this application has a current submission for `form_key`."""
        ...

    def has_current_at_round(self, form_key: str) -> bool:
        """True if the current submission was made at the application's round."""
        ...

    def form_data(self, form_key: str) -> Mapping[str, Any]:
        """The current submission's data, or an empty mapping."""
        ...

    def product_has_current(self, workflow_key: str, form_key: str) -> bool:
        """True if a sibling application on the same product has the claim."""
        ...


class FormDefinition:
    """One form a workflow collects. Subclasses are declarations, not objects.

    `editable_states` is what makes "the claim becomes editable on send-back"
    a mechanism instead of a hope, and what stops a REGISTRATION resubmission
    moving the solution-type ceiling under an already-granted decision.
    Repeatable forms are pure history: every submission is a distinct event
    and none is "current" (plan/09-redesign.md §3.2).
    """

    key: ClassVar[str]
    label: ClassVar[str]
    form_class: ClassVar[type[forms.Form]]
    depends_on: ClassVar[tuple[str, ...]] = ()
    required: ClassVar[bool] = True
    repeatable: ClassVar[bool] = False
    #: `DocumentKind` values the submission must carry evidence for
    requires_document: ClassVar[tuple[str, ...]] = ()
    schema_version: ClassVar[int] = 1
    #: `submit_form` refuses while the application is in any other state
    editable_states: ClassVar[frozenset[str]] = frozenset()
    actor_kind: ClassVar[ActorKind] = ActorKind.OWNER
    permission: ClassVar[str] = ""

    @classmethod
    def is_applicable(cls, ctx: Context) -> bool:
        return True

    @classmethod
    def is_unlocked(cls, ctx: Context) -> bool:
        return cls.is_applicable(ctx) and all(
            ctx.has_current(key) for key in cls.depends_on
        )


@dataclass(frozen=True, slots=True)
class TransitionSpec:
    """One legal edge of a workflow's state graph."""

    to_state: str
    actor_kind: ActorKind
    permission: str = ""
    #: names resolved against the hook registry at commit time
    hooks: tuple[str, ...] = field(default_factory=tuple)
    #: names resolved against the guard registry, run *before* the move and
    #: able to refuse it — kept on the spec so a console calling `transition()`
    #: generically cannot route around them
    guards: tuple[str, ...] = field(default_factory=tuple)
    #: the move advances `Application.round` (a rejected attempt's resubmission
    #: must be distinguishable from the attempt, and reviews are unique per round)
    advances_round: bool = False
    #: STAFF form the engine itself writes inside this transition — the decision
    #: and the move cannot exist without each other
    decision_form_key: str = ""
    #: the review row carries this decision's text, so the transition must not
    review_driven: bool = False


class Workflow:
    """A programme's complete flow: states, edges, forms. Declared, not stored.

    Subclasses live in `sandbox.programmes` and are looked up through
    `sandbox.workflow.registry` by the `workflow_key` column. Changing a flow
    is a code deploy — that lockdown is the point (plan/09-redesign.md §9.1).
    """

    key: ClassVar[str]
    label: ClassVar[str]
    #: the team's unit of authority. ABDM and its exit share one, because one
    #: team reviews both; HCX is a different programme and a different team.
    programme: ClassVar[str]
    #: name -> human label, created at migrate time from the registry
    permissions: ClassVar[dict[str, str]]
    #: seeing it in the console at all, so a queue can be scoped to a team
    view_permission: ClassVar[str]
    #: recording an opinion — deliberately grants no transition
    review_permission: ClassVar[str]
    initial_state: ClassVar[str]
    #: nothing more can ever happen to the application
    terminal_states: ClassVar[frozenset[str]]
    #: states that free the one-in-flight-per-(product, workflow) slot
    resting_states: ClassVar[frozenset[str]]
    transitions: ClassVar[dict[tuple[str, str], TransitionSpec]]
    forms: ClassVar[tuple[type[FormDefinition], ...]]

    @classmethod
    def form(cls, form_key: str) -> type[FormDefinition]:
        for definition in cls.forms:
            if definition.key == form_key:
                return definition
        message = f"{cls.key} has no form {form_key!r}"
        raise KeyError(message)

    @classmethod
    def permission_for(cls, action: str) -> str:
        """The permission gating `action`, for authority checks with no
        transition to ride on (retrying a teardown after a terminal state)."""
        for (_state, candidate), spec in cls.transitions.items():
            if candidate == action:
                return spec.permission
        message = f"{cls.key} has no action {action!r}"
        raise KeyError(message)

    @classmethod
    def states(cls) -> frozenset[str]:
        reachable = {cls.initial_state}
        for (from_state, _action), spec in cls.transitions.items():
            reachable.add(from_state)
            reachable.add(spec.to_state)
        return frozenset(reachable)

    @classmethod
    def actions_available(cls, state: str) -> tuple[str, ...]:
        """What the console may offer from `state`, before permission filtering."""
        return tuple(
            action for (from_state, action) in cls.transitions if from_state == state
        )
