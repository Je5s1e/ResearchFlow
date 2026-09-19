# ResearchFlow 工作流模块化重构与测试报告

## 1. 背景与目标

ResearchFlow 是基于 LangGraph 的终端论文调研系统，包含计划生成、人工审批、论文检索、证据提取、研究总结、写作和导出等步骤。

重构前，`researchflow/graph.py` 共 423 行，全部节点实现都嵌套在 `build_graph()` 内部。阅读完整流程时必须跨过大量业务代码；定位某个节点时，又需要在同一文件中查找。节点通过闭包隐式引用 `model`、`search` 和 `store`，也不便于独立测试。

本次按阶段重构方案，完成第一阶段：**将工作流拓扑与节点实现分离，每个注册节点独立一个 Python 文件，同时验证运行行为与旧会话兼容性。**

原有 `tools/papers.py`、CLI 主体和存储实现暂时保留，后续可以在当前测试基线上继续拆分。此次没有同时迁移到 `src/` 布局，也没有引入通用 Agent 框架。

## 2. 重构后的结构

```text
researchflow/
├── graph.py                         # 63 行：注册节点、声明边、编译图
├── schemas.py                       # 业务数据模型，兼容导出 State
├── workflow/
│   ├── __init__.py
│   ├── state.py                     # 持久化工作流状态
│   ├── dependencies.py              # 当前会话的模型、检索、存储依赖
│   ├── routes.py                    # 审批后的路由选择
│   ├── approvals.py                 # 审批暂停、校验与审批失效处理
│   ├── dispatch.py                  # 共享任务派发
│   ├── messages.py                  # 消息构造
│   └── nodes/
│       ├── __init__.py
│       ├── plan.py
│       ├── plan_approval.py
│       ├── dispatch_search.py
│       ├── search.py
│       ├── dispatch_summary.py
│       ├── summary.py
│       ├── material_approval.py
│       ├── dispatch_write.py
│       ├── write.py
│       └── export.py
├── __main__.py                      # 原 CLI 入口与运行管理
├── agents/                          # 原模型客户端
├── tools/                           # 原 MCP、PDF、论文与引用处理
├── storage.py
└── config.py

tests/
├── __init__.py
├── helpers.py                       # 合成论文、固定模型响应和本地测试 PDF
├── checkpoint_worker.py             # 跨进程 checkpoint 准备与恢复工具
├── test_workflow.py                 # 17 项工作流集成测试
├── test_approval_guards.py          # 6 项审批保护测试
└── test_cli.py                      # 6 项 CLI 与跨进程测试
```

`graph.py` 从 423 行缩减到 63 行，减少约 85%。这表示拓扑入口更集中，并不表示业务逻辑被删除或总代码量减少；模块说明、显式依赖和测试增加了项目总代码量。

## 3. 关键设计

### 3.1 每个节点对应一个模块

十个注册节点分别放入同名文件。例如，图中的 `search` 节点对应 `workflow/nodes/search.py`，`material_approval` 对应 `workflow/nodes/material_approval.py`。

普通节点使用统一形式：

```python
async def search_node(state: State, *, deps: WorkflowDependencies) -> dict:
    ...
```

同步审批和导出节点仍使用普通 `def`。节点读取状态、执行本阶段工作并返回局部状态更新，不负责连接图的边。

### 3.2 显式绑定运行依赖

`WorkflowDependencies` 是不可重新赋值字段的 dataclass，包含 `model`、`search`、`store` 三项依赖。它不意味着内部客户端本身不可变。

顶层通过 `functools.partial` 绑定当前会话的依赖：

```python
deps = WorkflowDependencies(model=model, search=search, store=store)
graph.add_node("search", partial(search_node, deps=deps))
```

依赖对象不进入 `State`，避免模型客户端或文件存储实例参与 checkpoint 序列化。`build_graph(model, search, store, checkpointer)` 的调用接口保持原样，因此 CLI 不需要更改调用方式。

### 3.3 节点独立、公共逻辑共享

两个审批节点调用 `approvals.py` 中的 `process_approval()`；三个派发节点调用 `dispatch.py` 中的 `dispatch_task()`。这样既能按节点名称定位源码，也避免复制审批规则和派发逻辑。

原来嵌入图构造函数的两个路由 lambda 被替换为有名称的函数。图构造处显式声明所有可能目标，便于阅读修改回路及查看图结构。

### 3.4 保持持久化与业务行为

保留节点注册名、State 字段、阶段值、审批载荷、产物名称和 `build_graph()` 参数。将 State 移动到 `workflow/state.py`，同时在 `schemas.py` 中保留兼容导入。

提示词、模型调用顺序、审批校验、搜索策略、引用检查和产物写入逻辑均按原逻辑迁移。另对五个主要节点、共享审批处理与共享派发处理进行了 AST 对比：排除新增说明、依赖解包以及 `s` 改名为 `state` 后，业务函数体一致。

## 4. 遇到的问题与解决方案

| 问题或约束 | 具体表现 | 解决方案与验证 |
|---|---|---|
| 节点依赖隐藏在闭包里 | 将内部函数直接搬到文件后，原作用域中的模型、检索和存储对象不再可见 | 通过 `WorkflowDependencies` 显式传入，由 `partial` 在构图时绑定；完整流程测试通过 |
| 独立节点容易造成重复代码 | 两个审批节点和三个派发节点实现相近 | 节点文件仅指定 gate、stage、role，共享业务处理集中实现 |
| `interrupt()` 恢复时会重新执行节点开头 | 如果在暂停之前写入产物或调用模型，恢复时可能重复执行副作用 | 保留暂停前的只读文件校验；恢复测试检查计划和材料不会重新生成 |
| 旧 checkpoint 可能受移动模块影响 | 仅测试新建任务不能证明旧会话能恢复 | 在修改源码前分别保存计划审批和材料审批 checkpoint，修改后用新进程恢复并完成导出，两者均通过 |
| 首轮测试出现 macOS 路径断言误报 | Store 使用解析后的 `/private/var/...` 路径，临时目录原始路径可能为 `/var/...`，直接判断父子关系失败 | 两侧统一使用 `Path.resolve()`；首次 17 项测试中唯一失败为此测试断言，修正后原代码 17 项全部通过 |
| 系统 Python 与项目 Python 不一致 | 最后一次额外导入检查误用系统 `python3` 3.9.6，执行 `str \| None` 注解时报 TypeError；项目声明要求 Python 3.11–3.12 | 改用项目 `.venv/bin/python` 3.12.13 后检查通过；文档统一推荐 `uv run --locked`，不为错误解释器修改业务源码 |
| 跨进程测试必须保留审批所绑定的 PDF 内容 | FakeSearch 初始化如果重新生成已有 PDF，会改变文件内容及哈希 | 测试夹具仅在 PDF 不存在时生成；恢复时复用文件，材料审批跨进程测试通过 |
| 只测试正常路径无法证明审批保护有效 | 错误请求 ID、旧版本、文件篡改或直接调用执行节点都可能成为遗漏场景 | 添加负向集成测试及独立审批保护测试，检查在调用模型、检索或导出之前拒绝执行 |
| 外部服务响应不稳定，难以作为确定性回归标准 | 模型文本和搜索结果可能变化，真实 API 也存在费用和网络依赖 | 自动化测试替换模型与搜索边界，保留真实图、SQLite、Store、PDF 提取及 CLI；真实 MCP 连通性单独用 doctor 验证 |
| 仓库忽略了整个 `docs/` 目录 | 原 `.gitignore` 包含 `/docs/`，新报告放入该目录会默认被忽略 | 报告放在根目录 `REFACTORING_REPORT.md`，并由 README 链接，不修改原忽略策略 |

此次未发现需要改变生产业务行为才能通过回归测试的问题；记录中的路径误报、解释器选择和 PDF 夹具处理属于环境与测试设计问题。

## 5. 测试方法与结果

### 5.1 测试环境

- 实际验证环境：macOS、Python 3.12.13、项目现有 `.venv` 与锁定依赖。
- 重构前 Git 基线：`33d3925`；本次重构未创建提交。
- 测试框架：Python 标准库 `unittest`，异步测试使用 `IsolatedAsyncioTestCase`，无需新增测试依赖。
- 模型和检索使用固定合成数据；不读取真实 API 密钥进行模型请求。
- PDF 使用 PyMuPDF 生成本地合成论文，实际执行文字提取、逐块证据处理和引用检查。
- checkpoint 使用真实 SQLite 文件；不是内存 checkpointer 的替代测试。
- 测试会话使用临时目录，正常结束后自动清理，不写入已有 `sessions/`。

### 5.2 验证顺序

1. 在原实现上执行 17 项工作流测试，修正测试路径断言后全部通过，建立行为基线。
2. 用原实现生成两个待审批的 SQLite checkpoint，分别位于计划审批和材料审批。
3. 执行节点与共享逻辑拆分，在新实现上运行相同 17 项测试，全部通过。
4. 在独立新进程中恢复两个旧实现 checkpoint，均完成报告导出。
5. 补充审批保护、CLI 生命周期、独立进程恢复测试，最终 29 项全部通过。
6. 执行 Ruff、格式检查、Git 差异空白检查，以及真实 MCP doctor 诊断。

### 5.3 自动化测试覆盖

| 范围 | 已验证的行为 |
|---|---|
| 正常流程 | 计划审批前不检索；材料审批前不写作；最终导出 Markdown 与 BibTeX，并验证产物哈希 |
| 计划修改 | 生成新版本与新请求 ID；清空审批；旧审批请求不能批准新计划 |
| 材料修改 | 分别回到总结、检索或计划；总结修改复用搜索结果；检索修改推进轮次；计划修改清空下游数据 |
| 审批输入 | 错误请求 ID、错误版本被拒绝；修改轮数超过 10 轮被拒绝 |
| 审批授权链 | 哈希不匹配、缺少上游计划审批、材料指向旧计划、审批后文件被改动均被拒绝 |
| 文件完整性 | 计划文件被修改或材料文件丢失时不能继续 |
| 节点独立保护 | 直接调用 search、write、export，也必须满足审批要求 |
| 证据与引用 | 无效论文 ID、不匹配原文的摘录、不通过的材料审查、未知报告引用不能进入后续合法产出 |
| 失败重试 | 检索失败后恢复原 checkpoint；引用错误修正后重试完成导出 |
| 恢复 | 关闭并重新打开 SQLite 后保留两个审批点；独立进程恢复两个审批点 |
| CLI | run、quit、resume、retry、status、list；待审批时 retry 不能绕过审批 |
| 重复执行 | CLI 再次 resume 已完成会话不重复写作；消息审计无重复事件；已完成图以空输入继续不重写报告 |
| 测试隔离 | 输出保持在解析后的临时目录中 |

### 5.4 实际执行结果

自动化测试：

```text
$ .venv/bin/python -m unittest discover -v
Ran 29 tests in 7.110s
OK
```

重构前创建的 checkpoint，在重构后由新进程恢复：

```text
finish plan: OK
finish material: OK
```

静态与格式检查：

```text
$ .venv/bin/ruff check researchflow tests
All checks passed!

$ .venv/bin/ruff format --check researchflow/graph.py researchflow/schemas.py researchflow/workflow tests
26 files already formatted

$ git diff --check
无错误输出
```

真实连接诊断：

```text
$ uv run --locked python -m researchflow doctor
模型配置：已填写
arxiv MCP：连接成功，search_papers
scholar MCP：连接成功，search_google_scholar
```

这里的“连接成功”是启动真实 MCP 服务并发现预期工具及参数，不代表已经向 arXiv 或 Google Scholar 提交检索请求。

### 5.5 复现命令

在仓库根目录执行：

```bash
uv sync --locked
uv run --locked python -m unittest discover -v
uv run --locked ruff check researchflow tests
uv run --locked ruff format --check researchflow/graph.py researchflow/schemas.py researchflow/workflow tests
git diff --check
uv run --locked python -m researchflow doctor
```

29 项测试已包含独立进程恢复检查。若需单独观察 checkpoint，可以指定一个测试目录，依次运行：

```bash
uv run --locked python -m tests.checkpoint_worker prepare /tmp/researchflow-checkpoint-demo plan
uv run --locked python -m tests.checkpoint_worker finish /tmp/researchflow-checkpoint-demo plan
```

将最后一个参数换成 `material`，可以验证材料审批恢复。这个手动示例会保留指定目录中的合成测试产物，便于检查；需要使用新的测试目录，避免覆盖之前的 `.session` 指针文件。

注意：在当前代码上依次执行 prepare/finish 只能复现“当前版本的跨进程恢复”。本次跨版本验证是在修改代码前执行 prepare、修改后执行 finish；再次复现跨版本验证时，也需要使用重构前实现准备 checkpoint，再切换到重构后实现恢复。

## 6. 验证边界

本次结果证明：重构后的确定性离线完整流程、审批与修改路径、主要失败保护、CLI 生命周期、持久化恢复，以及两个旧实现审批 checkpoint 的兼容性均已通过实际测试。

以下内容没有在本次工作中验证，不应在作业汇报中表述为已经完成：

- 使用真实模型 API、实时搜索结果和真实论文下载执行一次完整调研。
- 真实模型输出的研究结论质量、所有网络异常或所有历史会话的兼容性。
- Python 3.11 的独立环境测试；本次实际运行版本为 3.12.13。

真实端到端调研可以沿用原命令启动：

```bash
uv run --locked python -m researchflow run --topic "你的调研需求"
```

该过程仍需要用户分别批准计划和材料。模型配置已填写的诊断结果只说明配置存在，不证明密钥、额度或模型服务当前可用。

## 7. 可用于作业汇报的总结

本次重构将 ResearchFlow 的工作流拓扑与节点实现分离，把原先集中在 423 行 `graph.py` 中的节点拆为十个独立模块，顶层图文件缩减至 63 行。通过显式依赖注入和共享审批、派发模块，提高了源码可读性与节点可测试性，同时保留原有节点名、状态字段、审批协议及存储行为。采用先建立基线、再迁移实现、最后补充负向与恢复测试的方法，最终通过 29 项自动化测试，并验证了两个重构前审批 checkpoint 在新代码中的恢复与导出。真实 arXiv 和 Scholar MCP 服务连接及工具发现通过；完整真实模型调研尚未执行，因此将其与已验证的离线完整流程明确区分。

## 8. 后续迭代方向

下一阶段可以把 `tools/papers.py` 中的论文归一化、PDF 下载、证据提取和引用处理拆成独立能力模块，并将 CLI 展示与执行管理分离。每次拆分继续运行现有回归测试，保持审批、修改回路和恢复语义稳定。
