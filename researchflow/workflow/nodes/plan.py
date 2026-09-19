import uuid
from datetime import date

from researchflow.schemas import Plan
from researchflow.storage import json_text
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.messages import message
from researchflow.workflow.state import State


async def plan_node(state: State, *, deps: WorkflowDependencies) -> dict:
    """Generate a plan and invalidate downstream state before requesting approval."""
    model, store = deps.model, deps.store
    plan = await model.ask(
        "调度 Agent",
        "根据用户本次需求生成可执行调研计划。默认30篇候选、10篇入选；默认中文3000–5000字。未要求日期则不限定；相对日期转换为明确日期。queries 为适合 arXiv 的英文查询词。只在需要跨来源补充时开启 scholar_supplement。尊重修改反馈。",
        {
            "request": state["request"],
            "today": date.today().isoformat(),
            "previous": state.get("plan"),
            "feedback": state.get("feedback", ""),
        },
        Plan,
    )
    data = plan.model_dump()
    ref, version = store.artifact("01_调研计划", "json", json_text(data))
    md, _ = store.artifact(
        "01_调研计划", "md", "# 调研计划\n\n```json\n" + json_text(data) + "\n```\n"
    )
    rid = uuid.uuid4().hex
    msg = message(state, "调度 Agent", "用户", "请审批调研计划。", rid, [ref, md])
    return {
        "plan": data,
        "plan_version": version,
        "plan_refs": [ref, md],
        "plan_request_id": rid,
        "approvals": [],
        "papers": [],
        "evidence": [],
        "material": {},
        "material_refs": [],
        "search_refs": [],
        "search_round": 0,
        "report": {},
        "report_refs": [],
        "stage": "plan_approval",
        "messages": state.get("messages", []) + [msg],
    }
