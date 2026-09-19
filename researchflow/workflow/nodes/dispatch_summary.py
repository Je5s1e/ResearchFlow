"""Dispatch the summary task to its execution role."""

from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.dispatch import dispatch_task
from researchflow.workflow.state import State


async def dispatch_summary_node(state: State, *, deps: WorkflowDependencies) -> dict:
    return await dispatch_task(state, "summary", "总结 Agent", deps=deps)
