"""Pure routing decisions; graph.py declares their possible destinations."""

from typing import Literal

from researchflow.workflow.state import State


def route_after_plan_approval(state: State) -> Literal["plan", "dispatch_search"]:
    return "plan" if state["stage"] == "revise_plan" else "dispatch_search"


def route_after_material_approval(
    state: State,
) -> Literal["plan", "dispatch_search", "dispatch_summary", "dispatch_write"]:
    return {
        "revise_plan": "plan",
        "revise_search": "dispatch_search",
        "revise_summary": "dispatch_summary",
        "write": "dispatch_write",
    }[state["stage"]]
