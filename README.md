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

## 示例运行视频

<video controls preload="metadata" width="720" src="https://raw.githubusercontent.com/Je5s1e/ResearchFlow/main/sessions/20260919_152133_%E8%B0%83%E7%A0%94%E8%BF%91%E5%8D%8A%E5%B9%B4_Coding_agent_%E7%9A%84%E8%BF%9B%E5%B1%95_819b90cd/%E7%A4%BA%E4%BE%8B%E8%BF%90%E8%A1%8C%E8%A7%86%E9%A2%91.mp4">
  当前环境不支持内嵌播放，请<a href="https://raw.githubusercontent.com/Je5s1e/ResearchFlow/main/sessions/20260919_152133_%E8%B0%83%E7%A0%94%E8%BF%91%E5%8D%8A%E5%B9%B4_Coding_agent_%E7%9A%84%E8%BF%9B%E5%B1%95_819b90cd/%E7%A4%BA%E4%BE%8B%E8%BF%90%E8%A1%8C%E8%A7%86%E9%A2%91.mp4">打开示例运行视频</a>。
</video>
