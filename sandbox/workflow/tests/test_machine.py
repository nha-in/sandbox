"""The graph itself: exhaustive over every (state, action) pair."""

from __future__ import annotations

import pytest

from sandbox.applications.models import ApplicationState
from sandbox.workflow.machine import LEGAL_EDGES
from sandbox.workflow.machine import TRANSITIONS
from sandbox.workflow.machine import Action
from sandbox.workflow.machine import ActorKind
from sandbox.workflow.machine import actions_available

ALL_PAIRS = [(state, action) for state in ApplicationState for action in Action]
ILLEGAL_PAIRS = [pair for pair in ALL_PAIRS if pair not in TRANSITIONS]


def test_every_pair_is_either_declared_or_illegal():
    assert len(ALL_PAIRS) == len(TRANSITIONS) + len(ILLEGAL_PAIRS)
    assert len(TRANSITIONS) == len(LEGAL_EDGES)  # no duplicate edges


@pytest.mark.parametrize(("state", "action"), sorted(TRANSITIONS))
def test_legal_pair_targets_a_real_state(state, action):
    spec = TRANSITIONS[(state, action)]

    assert spec.to_state in ApplicationState.values
    assert spec.to_state != state, f"{state} -{action}-> itself is a no-op"


@pytest.mark.parametrize(("state", "action"), ILLEGAL_PAIRS)
def test_illegal_pair_is_absent(state, action):
    assert (state, action) not in TRANSITIONS


def test_system_moves_never_require_a_permission():
    """A permission implies a person; the chain has none to check."""
    for (state, action), spec in TRANSITIONS.items():
        if spec.actor_kind is ActorKind.SYSTEM:
            assert not spec.permission, f"{state} -{action}-> carries a permission"


def test_staff_moves_always_require_a_permission():
    """Otherwise any logged-in user could approve — the legacy failure mode."""
    for (state, action), spec in TRANSITIONS.items():
        if spec.actor_kind is ActorKind.STAFF:
            assert spec.permission, f"{state} -{action}-> has no permission"


def test_owner_moves_never_require_a_permission():
    for (state, action), spec in TRANSITIONS.items():
        if spec.actor_kind is ActorKind.OWNER:
            assert not spec.permission, f"{state} -{action}-> gates an owner move"


def test_terminal_states_have_no_outgoing_moves_except_reapplication():
    """REJECTED and WITHDRAWN end the application; a new one is a new row."""
    for state in (ApplicationState.REJECTED, ApplicationState.WITHDRAWN):
        assert actions_available(state) == ()


def test_every_state_is_reachable():
    """A state nothing can reach is dead code in the enum."""
    reachable = {spec.to_state for spec in TRANSITIONS.values()}
    reachable.add(ApplicationState.DRAFT)  # the entry point, created by A3

    unreachable = set(ApplicationState.values) - reachable
    assert not unreachable, f"unreachable states: {sorted(unreachable)}"


def test_provisioning_is_only_entered_by_the_chain_or_a_retry():
    entries = {
        (state, action)
        for (state, action), spec in TRANSITIONS.items()
        if spec.to_state == ApplicationState.PROVISIONING
    }

    assert entries == {
        (ApplicationState.SANDBOX_APPROVED, Action.START_PROVISIONING),
        (ApplicationState.PROVISIONING_FAILED, Action.RETRY_PROVISIONING),
    }


def test_actions_available_filters_by_state():
    assert set(actions_available(ApplicationState.DRAFT)) == {
        Action.SUBMIT,
        Action.WITHDRAW,
    }


def test_review_driven_actions_are_exactly_the_recorded_decisions():
    """A6 writes a review row for these; anything else keeps its own comment."""
    review_driven = {
        action for (_state, action), spec in TRANSITIONS.items() if spec.review_driven
    }

    assert review_driven == {
        Action.APPROVE,
        Action.REJECT,
        Action.SEND_BACK,
        Action.APPROVE_EXIT,
        Action.REJECT_EXIT,
        Action.SEND_BACK_EXIT,
    }


def test_only_staff_moves_are_review_driven():
    for (state, action), spec in TRANSITIONS.items():
        if spec.review_driven:
            assert spec.actor_kind is ActorKind.STAFF, f"{state} -{action}->"
