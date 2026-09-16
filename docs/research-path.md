# 调研与验证记录

## 技术资料与取舍

| 资料 | 采用内容与理由 |
| --- | --- |
| https://docs.langchain.com/oss/python/langgraph/interrupts | 审批用 interrupt + Command；审批节点和内容生成节点分开，避免恢复重做模型请求 |
| https://docs.langchain.com/oss/python/langgraph/persistence | 按会话 thread_id 保存状态，用 SQLite 支持退出和恢复 |
| https://github.com/modelcontextprotocol/python-sdk | 使用 stdio_client + ClientSession 调用 MCP，不依赖 IDE 或其他应用 |
| https://github.com/blazickjp/arxiv-mcp-server/tree/v0.7.2 | 核对 search_papers 参数和返回结构，固定 0.7.2；download_paper 不保证原始 PDF，所以另行下载 |
| https://github.com/JackKuo666/Google-Scholar-MCP-Server/tree/738d60a4d69464731e7c5b3a61767c06ff2cec0d | 核对网页检索逻辑；最小适配补充超时、参数编码、错误识别、PDF 链接和片段标注 |
| https://pymupdf.readthedocs.io/ | 本地提取 PDF 文字和页码；不引入 OCR 服务或复杂解析框架 |

未使用向量库、Web 服务、后台队列。四个角色共享模型客户端，由独立提示词与固定节点承担不同职责。使用纯 JSON + Pydantic 校验以适配不同模型服务。

## 关键源码

- `researchflow/graph.py`：固定工作流、调度任务交接、版本审批、材料检查、引用校验和导出。
- `researchflow/__main__.py`：终端交互、退出、恢复和重试。
- `researchflow/storage.py`：独立会话目录、版本产物、哈希、原子写入和日志。
- `researchflow/tools/mcp_client.py`：MCP 进程、工具调用、限速和检索快照。
- `researchflow/tools/papers.py`：去重、PDF 下载、提取、证据摘录校验和文献导出。
- `tests/`：用假模型验证审批约束，用内存 PDF 验证下载与证据链，不依赖外网。

## 实际遇到的问题

1. **摘要与全文混淆**：Scholar 返回的是搜索片段，不能作为论文完整摘要。增加读取范围，片段不生成研究结论；PDF 或真实摘要才进入证据提取。
2. **MCP 返回错误不一定是协议异常**：arXiv 可能用 JSON status 表示限流/错误，客户端同时检查业务状态，不能把失败当空结果。
3. **恢复重复执行**：LangGraph 从中断节点开头恢复。审批独立成节点，下载和模型调用置于其他节点，工具重试仍需有效审批。
4. **版本审批不等于文件审批**：审批同时绑定产物文件哈希；手动改文件后旧审批不能继续执行。
5. **真实 PDF 的摘录差异**：真实测试中模型摘录未能严格匹配提取文本。归一化 PDF 断行连字符和 Unicode 连字；仍不匹配的摘录丢弃，并记录对应限制。逐页调用较慢，因此将文字合并为 12000 字符的块，保留页码映射，最多并发 3 个块并缓存已完成结果。
6. **补充检索不能复用同一页**：材料退回选择补充检索后，从批准查询的下一批结果继续，修改计划后重置分页。测试验证新结果请求与重新审批。
7. **依赖下载超时**：部分大 wheel 下载超时，使用分段下载并核对 PyPI SHA256 后安装到项目 `.venv`。临时下载脚本不属于系统代码，项目仍使用标准 `uv.lock` 和 `uv sync --locked`。
8. **引用不能重复维护**：真实写作在正文引用与模型额外声明的引用清单校验处失败。改为由程序从正文解析引用 ID，支持合并引用，并校验是否属于批准材料；保存写作草稿便于排查。
9. **pytest 入口的导入路径**：项目从仓库直接运行，不建立额外安装包；在 pytest 配置中明确项目根目录，确保 `uv run pytest` 与 `python -m pytest` 都能导入。

## 验证范围

当前 17 项测试通过，`ruff check` 通过，`uv sync --locked --offline` 已核验当前环境满足锁定依赖。

- 单元与流程测试覆盖两次审批、旧版本失效、文件被修改、材料修订、退出恢复、重复审批、失败重试、会话隔离、PDF 下载提取、摘要降级、片段隔离、无效引文丢弃。
- MCP 工具发现：arXiv 和 Scholar 均成功。
- Scholar 真实查询：成功返回 2 条结果，见 `examples/scholar-check.json`。
- 离线 CLI 已完整运行，产出见 `examples/offline/`，所有内容明确标注为模拟。
- 真实模型与 arXiv 已跑通：5 篇候选、3 篇入选，2 篇全文、1 篇摘要；经历暂停恢复与材料退回修改，最终批准材料 v2。27 条证据摘录匹配原文，最终引用与产物哈希校验通过。产出与校验记录见 `examples/real/`。

PyMuPDF 在当前版本中会产生 SWIG 弃用提示，不影响测试通过。引用集合校验和摘录匹配只能检查来源关联，不能证明全部学术结论正确，最终仍需人工审阅。
