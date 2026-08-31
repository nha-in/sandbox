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


def get_workflow(workflow_key: str) -> type[Workflow]:
    try:
        return WORKFLOWS[workflow_key]
    except KeyError:
        message = f"no workflow registered for key {workflow_key!r}"
        raise LookupError(message) from None
