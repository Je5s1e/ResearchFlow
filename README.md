# ResearchFlow

基于 LangGraph 的终端论文调研系统，支持 MCP 检索、PDF 下载、总结与报告生成，关键阶段需人工审批。结果保存在 `sessions/`。

## 工作流程

```text
用户需求 → 调度 Agent 制定计划 → 人工审批计划
        → 检索 Agent 检索论文、下载 PDF、提取证据
        → 总结 Agent 生成总结与提纲 → 人工审批材料
        → 写作 Agent 生成报告 → Markdown + BibTeX
```

两次审批均支持 `approve`（通过）、`revise`（反馈修改）、`quit`（保存退出）。计划未通过不执行检索，材料未通过不执行最终写作。

每次新任务在 `sessions/` 中创建独立会话目录，保存论文 PDF、逐篇笔记、阶段文档和最终报告。

## 启动

```bash
uv sync --locked
# 首次配置时执行，已有 .env 则跳过
cp .env.example .env
```

在 `.env` 中填写 `MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME`，然后启动：

```bash
uv run python -m researchflow
```

也可直接指定需求：

```bash
uv run python -m researchflow run --topic "调研近一年代码 Agent 的进展"
```

## 源码阅读顺序

1. [`researchflow/graph.py`](researchflow/graph.py)：完整流程拓扑，只注册节点、连接边并编译图。
2. [`researchflow/workflow/state.py`](researchflow/workflow/state.py)：checkpoint 中保存的状态字段。
3. [`researchflow/workflow/nodes/`](researchflow/workflow/nodes/)：每个 graph 节点对应一个同名模块。
4. [`researchflow/workflow/routes.py`](researchflow/workflow/routes.py)：审批后的分支选择。
5. `workflow/approvals.py`、`dispatch.py`、`messages.py`：共享审批、任务派发和消息构造。
6. `agents/model.py`、`tools/`、`storage.py`：模型、论文处理、外部工具与持久化实现。

节点采用 `node(state, *, deps)` 接口。`WorkflowDependencies` 保存当前会话的模型、检索与存储依赖，
由 `graph.py` 绑定；这些运行资源不写入 checkpoint。`schemas.State` 保留兼容导入。

## 测试与检查

```bash
uv sync --locked
uv run --locked python -m unittest discover -v
uv run --locked ruff check researchflow tests
uv run --locked python -m researchflow doctor
```

自动化测试使用合成论文和固定模型响应，不需要 API 密钥，也不调用外部检索；实际运行 LangGraph、
SQLite、PDF 文字提取、审批、CLI 交互逻辑与报告导出。所有测试会话位于自动清理的临时目录。
`doctor` 单独检查真实 MCP 连接与工具发现，不代表真实模型生成或搜索结果质量已经验证。

重构设计、问题与解决方案、测试结果及验证边界见 [重构与测试报告](REFACTORING_REPORT.md)。
