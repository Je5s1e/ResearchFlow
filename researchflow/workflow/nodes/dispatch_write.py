"""Dispatch the write task to its execution role."""

from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.dispatch import dispatch_task
from researchflow.workflow.state import State


async def dispatch_write_node(state: State, *, deps: WorkflowDependencies) -> dict:
    return await dispatch_task(state, "write", "写作 Agent", deps=deps)
