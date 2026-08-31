"""The ABDM programme's acceptance criteria, as tests.

The scenario table is plan/09-redesign.md §6 verbatim — the worked examples
from the NHA flow spec. Everything here runs without a database: the matrix,
the DAG and the four predicates are pure code, which is the point.
"""

from __future__ import annotations

import pytest

from sandbox.programmes.abdm import MILESTONE_PREREQS
from sandbox.programmes.abdm import SOLUTION_TYPE_MILESTONES
from sandbox.programmes.abdm import ABDMExitWorkflow
from sandbox.programmes.abdm import ABDMWorkflow
from sandbox.programmes.abdm import ExitGrant
from sandbox.programmes.abdm import Milestone
from sandbox.programmes.abdm import RegistrationSolutionType
from sandbox.programmes.abdm import SolutionType
from sandbox.programmes.abdm import dhis_enabled
from sandbox.programmes.abdm import exit_gate
from sandbox.programmes.abdm import is_compliant
from sandbox.programmes.abdm import milestone_form_key
from sandbox.programmes.abdm import milestone_unlocked
from sandbox.workflow.definitions import ActorKind
from sandbox.workflow.registry import WORKFLOWS
from sandbox.workflow.registry import get_workflow

M = Milestone
S = SolutionType


def grant(covers: set[Milestone], types: set[SolutionType]) -> ExitGrant:
    return ExitGrant(covers=frozenset(covers), approved_types=frozenset(types))


# ---------------------------------------------------------------------------
# The scenario table (§6). Registration selects [HMIS, HEALTH_LOCKER]
# throughout; each row is (grants, enabled buttons, compliant?).

SCENARIOS = {
    "1-approved-but-nothing-enabled": (
        [grant({M.M1, M.M2, M.PHR}, {S.HMIS, S.HEALTH_LOCKER})],
        set(),
        False,
    ),
    "2-hmis-only": (
        [grant({M.M1, M.M2, M.M3, M.PHR}, {S.HMIS, S.HEALTH_LOCKER})],
        {S.HMIS},
        False,
    ),
    "3-both-rows-satisfied": (
        [
            grant(
                {M.M1, M.M2, M.M3, M.PHR, M.HEALTH_LOCKER},
                {S.HMIS, S.HEALTH_LOCKER},
            ),
        ],
        {S.HMIS, S.HEALTH_LOCKER},
        True,
    ),
    "4-legal-dag-path-no-row-satisfied": (
        [grant({M.M1, M.M3}, {S.HMIS})],
        set(),
        False,
    ),
    "5-admin-narrowed": (
        [grant({M.M1, M.M2, M.M3, M.PHR, M.HEALTH_LOCKER}, {S.HMIS})],
        {S.HMIS},
        True,  # compliance reads coverage, not the button set
    ),
    "6-round-1-rejected-contributes-nothing": (
        # a rejected round yields no grant at all; only round 2's decision counts
        [
            grant(
                {M.M1, M.M2, M.M3, M.PHR, M.HEALTH_LOCKER},
                {S.HMIS, S.HEALTH_LOCKER},
            ),
        ],
        {S.HMIS, S.HEALTH_LOCKER},
        True,
    ),
    "7-in-flight-exit-grants-nothing": (
        # exit 2 is under review: not approved, so it contributes no grant
        [grant({M.M1, M.M2, M.M3}, {S.HMIS})],
        {S.HMIS},
        False,
    ),
    "8-additive-union-across-exits": (
        [
            grant({M.M1, M.M2, M.M3}, {S.HMIS}),
            grant({M.PHR, M.HEALTH_LOCKER}, {S.HEALTH_LOCKER}),
        ],
        {S.HMIS, S.HEALTH_LOCKER},
        True,
    ),
}

SELECTED = [S.HMIS, S.HEALTH_LOCKER]


@pytest.mark.parametrize(
    ("grants", "enabled", "compliant"),
    SCENARIOS.values(),
    ids=SCENARIOS.keys(),
)
def test_scenario_table(grants, enabled, compliant):
    for solution_type in SolutionType:
        assert dhis_enabled(grants, solution_type) == (solution_type in enabled)
    assert is_compliant(SELECTED, grants) == compliant


def test_no_grants_enables_nothing_and_is_not_compliant():
    assert not any(dhis_enabled([], solution_type) for solution_type in SolutionType)
    assert not is_compliant(SELECTED, [])
    assert not is_compliant([], [grant(set(M), set(S))])


def test_a_grant_is_never_revoked_by_a_later_narrower_one():
    grants = [
        grant({M.M1, M.M2}, {S.LMIS}),
        grant({M.M3}, {S.HMIS}),
    ]
    # the union grows; LMIS stays enabled after the HMIS-only second exit
    assert dhis_enabled(grants, S.LMIS)
    assert dhis_enabled(grants, S.HMIS)


# ---------------------------------------------------------------------------
# The DAG and the exit gate, against a stub context.


class StubContext:
    def __init__(self, *, current=(), at_round=(), product=(), data=None) -> None:
        self._current = set(current)
        self._at_round = set(at_round)
        self._product = set(product)
        self._data = data or {}

    def has_current(self, form_key):
        return form_key in self._current

    def has_current_at_round(self, form_key):
        return form_key in self._at_round

    def form_data(self, form_key):
        return self._data.get(form_key, {})

    def product_has_current(self, workflow_key, form_key):
        return (workflow_key, form_key) in self._product


def test_the_dag_m3_does_not_require_m2():
    ctx = StubContext(current={milestone_form_key(M.M1)})
    assert milestone_unlocked(ctx, M.M3)
    assert milestone_unlocked(ctx, M.M2)


def test_the_dag_health_locker_requires_phr_but_not_m1():
    assert not milestone_unlocked(StubContext(), M.HEALTH_LOCKER)
    ctx = StubContext(current={milestone_form_key(M.PHR)})
    assert milestone_unlocked(ctx, M.HEALTH_LOCKER)


def test_the_dag_phr_and_m1_have_no_prerequisites():
    ctx = StubContext()
    assert milestone_unlocked(ctx, M.M1)
    assert milestone_unlocked(ctx, M.PHR)


def _exit_ctx(covers, *, declared=(), wasa_at_round=True):
    return StubContext(
        at_round={"WASA"} if wasa_at_round else set(),
        product={("ABDM", milestone_form_key(m)) for m in declared},
        data={"EXIT_CLAIM": {"covers": list(covers)}},
    )


def test_exit_gate_passes_when_covers_are_declared_and_wasa_is_current():
    assert exit_gate(_exit_ctx([M.M1, M.M2], declared=[M.M1, M.M2]))


def test_exit_gate_refuses_an_undeclared_milestone():
    assert not exit_gate(_exit_ctx([M.M1, M.M2], declared=[M.M1]))


def test_exit_gate_refuses_an_empty_claim():
    assert not exit_gate(_exit_ctx([], declared=[M.M1]))


def test_exit_gate_refuses_a_stale_wasa():
    ctx = _exit_ctx([M.M1], declared=[M.M1], wasa_at_round=False)
    assert not exit_gate(ctx)


# ---------------------------------------------------------------------------
# Registry and graph sanity — the shape every programme must keep.


def test_registry_resolves_both_workflows_and_refuses_unknown_keys():
    assert get_workflow("ABDM") is ABDMWorkflow
    assert get_workflow("ABDM_EXIT") is ABDMExitWorkflow
    with pytest.raises(LookupError):
        get_workflow("NOT_A_WORKFLOW")


@pytest.mark.parametrize("workflow", WORKFLOWS.values(), ids=WORKFLOWS.keys())
def test_graph_sanity(workflow):
    states = workflow.states()
    assert workflow.initial_state in states
    assert workflow.terminal_states <= states
    assert workflow.resting_states <= states
    for (from_state, _action), spec in workflow.transitions.items():
        # nothing leaves a terminal state
        assert from_state not in workflow.terminal_states
        assert spec.to_state in states
        if spec.actor_kind is ActorKind.STAFF:
            assert spec.permission, f"STAFF move to {spec.to_state} needs a permission"
        if spec.decision_form_key:
            definition = workflow.form(spec.decision_form_key)
            assert definition.actor_kind is ActorKind.STAFF


@pytest.mark.parametrize("workflow", WORKFLOWS.values(), ids=WORKFLOWS.keys())
def test_form_keys_are_unique_and_repeatable_forms_are_history_only(workflow):
    keys = [definition.key for definition in workflow.forms]
    assert len(keys) == len(set(keys))
    for definition in workflow.forms:
        if definition.repeatable:
            # a repeatable form never supersedes, so editability is its only gate
            assert definition.editable_states


def test_the_matrix_uses_only_registration_selectable_types():
    registration_values = set(RegistrationSolutionType.values)
    assert {t.value for t in SOLUTION_TYPE_MILESTONES} <= registration_values


def test_every_milestone_has_a_prereq_entry_and_a_form():
    assert set(MILESTONE_PREREQS) == set(Milestone)
    for milestone in Milestone:
        assert ABDMWorkflow.form(milestone_form_key(milestone)).required is False
