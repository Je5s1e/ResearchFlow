"""Shared approval processing and downstream authorization checks."""

from langgraph.types import interrupt

from researchflow.schemas import Decision
from researchflow.storage import digest, now
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.messages import message
from researchflow.workflow.state import State


def require_approval(state, gate, store):
    refs = state[f"{gate}_refs"]
    store.verify(refs)
    valid = any(
        a["gate"] == gate
        and a["request_id"] == state[f"{gate}_request_id"]
        and a["version"] == state[f"{gate}_version"]
        and a["hash"] == digest(refs)
        for a in state.get("approvals", [])
    )
    if not valid:
        raise ValueError(f"{gate} 未获得当前版本审批")
    if gate == "material":
        require_approval(state, "plan", store)
        if state["material"]["plan_version"] != state["plan_version"]:
            raise ValueError("材料不是基于当前计划生成")


def process_approval(state: State, gate: str, *, deps: WorkflowDependencies) -> dict:
    """Pause for a version-bound decision; only read/verify files before interrupt."""
    store = deps.store
    store.verify(state[f"{gate}_refs"])
    decision = Decision.model_validate(
        interrupt(
            {
                "gate": gate,
                "request_id": state[f"{gate}_request_id"],
                "version": state[f"{gate}_version"],
                "files": state[f"{gate}_refs"],
                "preview": state["plan"] if gate == "plan" else state["material"],
            }
        )
    )
    if (
        decision.request_id != state[f"{gate}_request_id"]
        or decision.version != state[f"{gate}_version"]
    ):
        raise ValueError("审批请求或版本已失效")
    store.verify(state[f"{gate}_refs"])
    if gate == "material":
        require_approval(state, "plan", store)
    approvals = list(state.get("approvals", []))
    event = {
        **decision.model_dump(),
        "gate": gate,
        "hash": digest(state[f"{gate}_refs"]),
        "time": now(),
    }
    if decision.action == "approve":
        approvals = [a for a in approvals if a["gate"] != gate] + [event]
        return {
            "approvals": approvals,
            "stage": "search" if gate == "plan" else "write",
            "feedback": "",
            "messages": state["messages"]
            + [message(state, "用户", "调度 Agent", "审批通过", decision.request_id)],
        }
    rounds = state.get("rounds", 0) + 1
    if rounds > 10:
        raise ValueError("本会话修改超过10轮，请创建新任务")
    target = "plan" if gate == "plan" else decision.target
    approvals = [] if target == "plan" else [a for a in approvals if a["gate"] == "plan"]
    return {
        "stage": "revise_" + target,
        "revision_target": target,
        "feedback": decision.feedback,
        "approvals": approvals,
        "rounds": rounds,
        "messages": state["messages"]
        + [message(state, "用户", "调度 Agent", decision.feedback, decision.request_id)],
    }
