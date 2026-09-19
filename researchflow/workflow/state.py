"""Persisted workflow fields. Keep keys stable for existing SQLite checkpoints."""

from typing import TypedDict


class State(TypedDict, total=False):
    session_id: str  # 当前会话的唯一标识
    request: str  # 用户提交的调研需求
    stage: str  # 当前工作流阶段
    feedback: str  # 用户最近一次修改意见
    revision_target: str  # 本轮需要修改的阶段
    rounds: int  # 累计修改轮数
    plan: dict  # 调研计划内容
    plan_version: int  # 当前计划版本号
    plan_refs: list[dict]  # 计划产物的文件引用
    plan_request_id: str  # 计划审批请求编号
    approvals: list[dict]  # 已通过的审批记录
    task: dict  # 当前 Agent 任务指令
    messages: list[dict]  # Agent 间通信记录
    papers: list[dict]  # 检索得到的论文列表
    evidence: list[dict]  # 论文证据与读取记录
    search_refs: list[dict]  # 检索阶段产物引用
    search_round: int  # 检索执行轮次
    material: dict  # 研究总结与写作提纲
    material_version: int  # 当前材料版本号
    material_refs: list[dict]  # 材料产物的文件引用
    material_request_id: str  # 材料审批请求编号
    report: dict  # 报告正文及引用信息
    report_refs: list[dict]  # 最终报告产物引用
