import argparse
import asyncio
import json
import shlex
import tempfile
from contextlib import asynccontextmanager

from filelock import FileLock, Timeout
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown

from researchflow.agents.model import Model
from researchflow.config import Settings
from researchflow.graph import build_graph
from researchflow.schemas import Decision
from researchflow.storage import Store
from researchflow.tools.mcp_client import SearchMCP

console = Console(markup=False)
FLOW = "计划 → [计划审批] → 检索/PDF → 总结/提纲 → [材料审批] → 写作 → 完成"


def session_store(settings, sid):
    root = settings.sessions.resolve()
    path = (root / sid).resolve()
    if path.parent != root or not (path / "session.json").is_file():
        raise ValueError("会话不存在")
    return Store(path)


@asynccontextmanager
async def workflow(settings, store):
    settings.require_model()
    model = Model(settings)
    search = SearchMCP(store)
    async with AsyncSqliteSaver.from_conn_string(str(store.path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, search, store, saver)
        yield graph, {"configurable": {"thread_id": store.path.name}, "recursion_limit": 150}


def ask_decision(payload, store):
    console.print(f"\n暂停：{payload['gate']} 审批，版本 {payload['version']}")
    for ref in payload["files"]:
        if ref["path"].endswith(".md") and "/artifacts/" in "/" + ref["path"]:
            console.print(f"文件：{store.resolve(ref['path'])}")
            if any(x in ref["path"] for x in ("01_", "03_", "04_")):
                console.print(Markdown(store.resolve(ref["path"]).read_text()))
    while True:
        answer = input("通过 approve / 修改 revise / 保存退出 quit > ").strip().lower()
        if answer in ("quit", "q"):
            return None
        if answer not in ("approve", "a", "revise", "r"):
            continue
        target, feedback = "plan", ""
        if answer in ("revise", "r"):
            if payload["gate"] == "material":
                target = input("修改目标 summary / search / plan [summary] > ").strip() or "summary"
                if target not in ("summary", "search", "plan"):
                    continue
            feedback = input("修改意见 > ").strip()
            if not feedback:
                console.print("请填写修改意见。")
                continue
        return Decision(
            request_id=payload["request_id"],
            version=payload["version"],
            action="approve" if answer in ("approve", "a") else "revise",
            target=target,
            feedback=feedback,
        ).model_dump()


async def execute(args, settings):
    if args.command == "run":
        settings.require_model()
        topic = args.topic or input("请输入调研需求 > ").strip()
        if not topic:
            raise ValueError("需求不能为空")
        store = Store.create(settings.sessions, topic)
        value = {
            "session_id": store.path.name,
            "request": topic,
            "stage": "plan",
            "rounds": 0,
            "messages": [],
            "approvals": [],
        }
    else:
        store = session_store(settings, args.id)
        value = None
    store.on_event = lambda e: (
        console.print(e.get("message", f"工具调用：{e.get('server', '')}.{e.get('tool', '')}"))
        if e["type"] in ("tool", "progress", "warning")
        else None
    )
    console.print(f"会话：{store.path}\n{FLOW}")
    with FileLock(str(store.path / ".lock"), timeout=0):
        try:
            async with workflow(settings, store) as (graph, config):
                snapshot = await graph.aget_state(config)
                if args.command == "retry" and snapshot.interrupts:
                    raise ValueError("当前等待审批，请使用 resume")
                if args.command != "run" and not snapshot.values:
                    value = {
                        "session_id": store.path.name,
                        "request": store.read_json("session.json")["request"],
                        "stage": "plan",
                        "rounds": 0,
                        "messages": [],
                        "approvals": [],
                    }
                if args.command != "run" and snapshot.values and not snapshot.next:
                    console.print(f"会话已结束：{store.path / 'report.md'}")
                    return
                seen = {m["id"] for m in snapshot.values.get("messages", [])}
                while True:
                    if snapshot.interrupts:
                        store.status("waiting_approval", error=None)
                        decision = ask_decision(snapshot.interrupts[0].value, store)
                        if decision is None:
                            console.print(
                                f"已暂停。续跑：python -m researchflow resume --id {shlex.quote(store.path.name)}"
                            )
                            return
                        value = Command(resume=decision)
                    async for updates in graph.astream(value, config=config, stream_mode="updates"):
                        for node, update in updates.items():
                            if node == "__interrupt__":
                                continue
                            console.print(f"完成阶段：{node}")
                            if isinstance(update, dict):
                                store.audit_messages(update)
                                for msg in update.get("messages", []):
                                    if msg["id"] not in seen:
                                        console.print(
                                            f"{msg['sender']} → {msg['receiver']}：{msg['content']}"
                                        )
                                        seen.add(msg["id"])
                                store.status(update.get("stage", node), error=None)
                    snapshot = await graph.aget_state(config)
                    store.audit_messages(snapshot.values)
                    if not snapshot.next:
                        store.status("completed", error=None)
                        console.print(f"\n完成：{store.path / 'report.md'}")
                        return
                    value = None
        except (KeyboardInterrupt, EOFError):
            store.status("paused")
            console.print("已退出，可使用 resume 继续。")
        except Exception as exc:
            error = (
                str(exc).replace(settings.api_key, "[REDACTED]") if settings.api_key else str(exc)
            )
            store.status("failed", error=error)
            console.print(
                f"执行失败：{error}\n重试：python -m researchflow retry --id {shlex.quote(store.path.name)}"
            )
            raise RuntimeError("会话已保留") from None


async def doctor(settings):
    console.print(
        f"模型配置：{'已填写' if settings.api_key and settings.model else '缺少 MODEL_API_KEY 或 MODEL_NAME'}"
    )
    with tempfile.TemporaryDirectory(prefix="researchflow-doctor-") as directory:
        store = Store.create(directory, "MCP connectivity")
        client = SearchMCP(store)
        for source, required in (("arxiv", "search_papers"), ("scholar", "search_google_scholar")):
            try:
                tools = await client.call(source)
                tool = next(t for t in tools if t["name"] == required)
                console.print(
                    f"{source} MCP：连接成功，{required}，参数 {list(tool['inputSchema']['properties'])}"
                )
            except Exception as exc:
                console.print(f"{source} MCP：失败 {type(exc).__name__}: {exc}")


def main():
    parser = argparse.ArgumentParser(description="ResearchFlow 终端论文调研")
    parser.add_argument("--sessions", help="会话根目录")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run")
    run.add_argument("--topic")
    for name in ("resume", "retry", "status"):
        sub.add_parser(name).add_argument("--id", required=True)
    sub.add_parser("list")
    sub.add_parser("doctor")
    args = parser.parse_args()
    if args.command is None:
        args.command, args.topic = "run", None
    settings = Settings.load(args.sessions)
    try:
        if args.command == "list":
            for p in sorted(settings.sessions.glob("*/session.json")):
                data = json.loads(p.read_text())
                console.print(
                    f"{p.parent.name} | {data.get('stage', 'created')} | {data['request']}"
                )
        elif args.command == "status":
            store = session_store(settings, args.id)
            console.print_json(data=store.read_json("session.json"))
        elif args.command == "doctor":
            asyncio.run(doctor(settings))
        else:
            asyncio.run(execute(args, settings))
    except Timeout:
        console.print("该会话正在另一个进程中执行。")
        raise SystemExit(1)
    except (ValueError, RuntimeError) as exc:
        console.print(str(exc))
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        console.print("已退出，已有会话可使用 resume 恢复。")


if __name__ == "__main__":
    main()
