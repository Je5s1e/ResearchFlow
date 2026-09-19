"""Approval gate for plan; behavior is shared between both gates."""

from researchflow.workflow.approvals import process_approval
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.state import State


def plan_approval_node(state: State, *, deps: WorkflowDependencies) -> dict:
    return process_approval(state, "plan", deps=deps)
