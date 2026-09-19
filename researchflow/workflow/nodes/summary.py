import uuid

from researchflow.schemas import Material, Review
from researchflow.storage import json_text
from researchflow.tools.papers import citations_valid
from researchflow.workflow.approvals import require_approval
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.messages import message, result_message
from researchflow.workflow.state import State


async def summary_node(state: State, *, deps: WorkflowDependencies) -> dict:
    """Build and review research material, then request material approval."""
    model, store = deps.model, deps.store
    require_approval(state, "plan", store)
    store.verify(state["search_refs"])
    usable = [n for n in state["evidence"] if n["findings"]]
    if not usable:
        raise ValueError("没有可支持总结的正文或摘要证据")
    feedback = state.get("feedback", "")
    allowed_ids = [n["paper_id"] for n in usable]
    for attempt in range(3):
        material = await model.ask(
            "总结 Agent",
            "基于证据生成中文研究总结、方法对比表、局限和写作提纲。每项研究结论使用 [@论文ID] 引用。只能使用以下论文 ID："
            + ", ".join(allowed_ids)
            + "。读取范围以 read_scope 和 read_blocks 为准，具体数值必须在对应 quote 中直接出现。不把搜索片段当证据。"
            + (" 上次输出引用非法，请纠正：" + feedback if feedback else ""),
            {"task": state["task"], "plan": state["plan"], "evidence": usable, "feedback": feedback},
            Material,
        )
        material_data = material.model_dump()
        try:
            material_data["cited_ids"] = citations_valid(material.summary + material.outline, allowed_ids)
            break
        except ValueError as exc:
            feedback = str(exc)
            if attempt == 2:
                raise
    review = await model.ask(
        "调度 Agent",
        "检查总结与提纲是否有证据支持、引用和读取范围是否诚实。不要发起新的工具调用。",
        {"material": material_data, "evidence": usable},
        Review,
    )
    if not review.acceptable:
        raise ValueError("材料检查未通过：" + review.comments)
    summary_ref, version = store.artifact("03_研究总结", "md", material.summary)
    outline_ref, _ = store.artifact("04_文档提纲", "md", material.outline)
    value = {
        **material_data,
        "plan_version": state["plan_version"],
        "review": review.comments,
        "evidence": state["evidence"],
        "papers": state["papers"],
    }
    bundle_ref, _ = store.artifact("material_bundle", "json", json_text(value))
    refs = state["plan_refs"] + state["search_refs"] + [summary_ref, outline_ref, bundle_ref]
    rid = uuid.uuid4().hex
    msgs = result_message(state, "总结 Agent", "研究总结和提纲已生成。", [summary_ref, outline_ref])
    msgs.append(
        message(
            state,
            "调度 Agent",
            "用户",
            "材料检查：" + review.comments + " 请审批材料与提纲。",
            rid,
            refs,
        )
    )
    return {
        "material": value,
        "material_version": version,
        "material_refs": refs,
        "material_request_id": rid,
        "stage": "material_approval",
        "messages": msgs,
    }
