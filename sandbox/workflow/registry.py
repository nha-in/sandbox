"""The workflow registry: `workflow_key` column value -> `Workflow` class.

The registry-sanity test (plan/09-redesign.md §9.1) asserts every persisted
`state`, `action`, `workflow_key` and `form_key` is known here — the CI gate
that makes "changes to workflows are very deliberate" operational.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.programmes.abdm import ABDMExitWorkflow
from sandbox.programmes.abdm import ABDMWorkflow

if TYPE_CHECKING:
    from sandbox.workflow.definitions import Workflow

WORKFLOWS: dict[str, type[Workflow]] = {
    workflow.key: workflow for workflow in (ABDMWorkflow, ABDMExitWorkflow)
}


def permission_labels() -> dict[str, str]:
    """Every permission the registry declares, name -> label.

    What `workflow.apps` creates at migrate time and what the sanity test
    checks against `named_permissions()`: `has_perm` answers False identically
    for "you lack it" and "nobody ever created it", so an uncreated name is a
    lockout with no error anywhere.
    """
    labels: dict[str, str] = {}
    for workflow in WORKFLOWS.values():
        labels.update(workflow.permissions)
    return labels


def named_permissions() -> frozenset[str]:
    """Every permission actually referenced by a workflow's gates."""
    names: set[str] = set()
    for workflow in WORKFLOWS.values():
        names.add(workflow.view_permission)
        names.add(workflow.review_permission)
        names.update(
            spec.permission for spec in workflow.transitions.values() if spec.permission
        )
    return frozenset(names)


def programme_for_permission(name: str) -> str:
    """Which programme a permission belongs to, for grouping it on screen."""
    for workflow in WORKFLOWS.values():
        if name in workflow.permissions:
            return workflow.programme
    return ""


def workflows_visible_to(user) -> tuple[str, ...]:
    """The workflow keys this actor may see at all — the console queue's scope."""
    return tuple(
        key
        for key, workflow in WORKFLOWS.items()
        if user.has_perm(workflow.view_permission)
    )


def get_workflow(workflow_key: str) -> type[Workflow]:
    try:
        return WORKFLOWS[workflow_key]
    except KeyError:
        message = f"no workflow registered for key {workflow_key!r}"
        raise LookupError(message) from None
