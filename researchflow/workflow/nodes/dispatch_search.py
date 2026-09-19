"""Dispatch the search task to its execution role."""

from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.dispatch import dispatch_task
from researchflow.workflow.state import State


async def dispatch_search_node(state: State, *, deps: WorkflowDependencies) -> dict:
    return await dispatch_task(state, "search", "检索 Agent", deps=deps)
