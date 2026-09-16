# ResearchFlow 技术选型与运行

## 最小技术栈

| 技术 | 用途 |
| --- | --- |
| Python 3.12 + uv | 独立环境、依赖锁定；兼容 3.11–3.12 |
| LangGraph | 固定 StateGraph、interrupt 审批、Command 恢复 |
| langgraph-checkpoint-sqlite | 每个会话独立 SQLite checkpoint |
| langchain-openai | 可配置兼容接口；JSON 输出经 Pydantic 校验，失败有限修正 |
| MCP Python SDK | stdio 启动工具进程、发现 schema、调用检索工具 |
| arxiv-mcp-server 0.7.2 | arXiv 检索，固定版本 |
| Scholar 本地 MCP 适配 | 基于核对的免费上游项目，HTTPX + BeautifulSoup，故障可降级 |
| HTTPX + PyMuPDF | 原始 PDF 下载、校验、逐页文字提取 |
| argparse + Rich | 命令与终端消息、Markdown 展示 |
| filelock + pathlib | 单会话互斥、原子写入与版本文件 |
| pytest | 审批、恢复、证据和 PDF 测试 |

不使用 Web 框架、任务队列、向量数据库或嵌套自主 Agent。引用 ID 由程序从正文解析，只允许批准材料中的来源；参考文献由元数据生成，写作草稿也保留为文件。

## 执行与审批

角色通过独立提示词实现，调度节点生成任务指令，执行节点读取指令与输入产物。固定图控制下一阶段，模型只生成内容。执行节点返回结果消息，终端展示并保存同一份消息。

审批节点只负责检查产物及 `interrupt()`；生成内容在前一节点完成，恢复不会重新生成待审内容。`Command(resume=decision)` 提交请求 ID、版本、决定、反馈与修改目标。批准计划才能检索；批准材料及提纲才能写作。执行前再次验证哈希和审批版本。

审批修改可回到计划、检索或总结；补充检索读取批准查询的下一批结果，调整查询主题则选择修改计划。新版本重新审批。SQLite 是运行状态来源，`session.json` 提供可读状态摘要。文件下载和模型调用不承诺恰好一次，重试可能重发模型请求；已下载 PDF 和同参数检索结果可复用。

## 检索与正文

`mcp.json` 保存项目 MCP 启动配置，程序自动管理进程，无需安装到其他应用。arXiv 优先；数量不足或批准计划要求时补充 Scholar。Scholar 失败明确记录，不自动改用付费服务。

默认候选上限 30、入选上限 10，计划可调整。检索结果按 ID、DOI、标题与作者去重，保存筛选理由。MCP 负责检索；程序单独保存原始 PDF，避免把 Markdown 转换结果当 PDF。

PDF 限制 50 MB，校验文件格式后保存。逐页提取正文，合并为不超过 12000 字符的块交给检索 Agent 生成证据，块请求并发最多 3 个并缓存结果；原文摘录须出现在对应文本中；归一化断行与连字后仍不匹配的摘录会丢弃并记录。记录页码、偏移和读取范围，不做 OCR/图表解析。正文失败退回真实摘要；Scholar 片段只作检索线索。

## 会话文件

```text
sessions/<时间_主题_短ID>/
  request.md, session.json, checkpoints.sqlite
  papers/       # ID_题名.pdf
  texts/        # 逐页 JSON、纯文本
  notes/        # 逐篇笔记与证据
  artifacts/    # 计划、论文清单、总结、提纲、材料包、报告、BibTeX
  logs/         # 对话、事件、MCP 请求结果和 stderr
  report.md     # 最新成功报告副本
```

产物文件名包含版本号，修订不覆盖。材料包引用相关证据和上游版本，审批绑定具体文件哈希。直接编辑待审文件会被拒绝，应恢复原文件并在终端提交修改反馈。`sessions/` 和 `.env` 不提交 Git；密钥不写入状态和日志。

## 运行

在仓库根目录执行：

```bash
uv sync --locked
cp .env.example .env
# 填写 MODEL_API_KEY、MODEL_BASE_URL、MODEL_NAME
uv run python -m researchflow doctor
uv run python -m researchflow
uv run python -m researchflow run --topic "近一年代码 Agent 的进展"
uv run python -m researchflow list
uv run python -m researchflow status --id <会话ID>
uv run python -m researchflow resume --id <会话ID>
uv run python -m researchflow retry --id <会话ID>
```

`doctor` 检查配置与 MCP 工具发现，不执行论文搜索。审批输入 `approve`、`revise` 或 `quit`。`resume` 重新显示原审批请求；`retry` 继续失败节点。可通过最前面的 `--sessions <目录>` 更换会话根目录。

无需密钥的流程演示：

```bash
uv run python -m researchflow run --demo --topic "演示审批与恢复"
uv run pytest -q
```

演示使用固定模拟数据，不代表模型输出或真实论文检索，不下载 PDF。最终报告明确标注演示性质。
