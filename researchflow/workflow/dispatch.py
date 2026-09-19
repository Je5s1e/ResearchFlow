"""Shared task dispatch for search, summary and writing."""

import uuid

from researchflow.schemas import Instruction
from researchflow.workflow.approvals import require_approval
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.messages import message
from researchflow.workflow.state import State


async def dispatch_task(state: State, stage: str, role: str, *, deps: WorkflowDependencies) -> dict:
    """Create a role-specific task using the approved inputs."""
    model, store = deps.model, deps.store
    require_approval(state, "material" if stage == "write" else "plan", store)
    refs = (
        state["material_refs"]
        if stage == "write"
        else state["plan_refs"] + state.get("search_refs", [])
    )
    task_id = uuid.uuid4().hex
    instruction = await model.ask(
        "调度 Agent",
        f"为{role}生成简短的本阶段任务指令及预期产物（不超过400字）。必须遵守已批准计划，不扩大范围；结合反馈。仅支持 arXiv MCP、Google Scholar MCP、公开 PDF 下载与文字提取，禁止要求其他来源或额外工具。",
        {
            "stage": stage,
            "plan": state["plan"],
            "feedback": state.get("feedback", ""),
            "material": state.get("material", {}),
        },
        Instruction,
    )
    task = {
        "id": task_id,
        "sender": "调度 Agent",
        "receiver": role,
        "stage": stage,
        "input_refs": refs,
        **instruction.model_dump(),
    }
    msg = message(state, "调度 Agent", role, task["instruction"], task_id, refs)
    return {"task": task, "stage": stage, "messages": state["messages"] + [msg]}
