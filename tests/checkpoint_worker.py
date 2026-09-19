"""Subprocess fixture for checkpoint compatibility; never uses real external services."""

import argparse
import asyncio
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from researchflow.graph import build_graph
from researchflow.storage import Store
from tests.helpers import FakeModel, FakeSearch, decision, initial_state


async def run(mode, root, gate):
    marker = root / f"{gate}.session"
    if mode == "prepare":
        store = Store.create(root, "离线跨进程恢复测试")
        marker.write_text(str(store.path))
    else:
        store = Store(marker.read_text())
    model, search = FakeModel(), FakeSearch(store)
    config = {"configurable": {"thread_id": store.path.name}, "recursion_limit": 150}
    async with AsyncSqliteSaver.from_conn_string(str(store.path / "checkpoints.sqlite")) as saver:
        graph = build_graph(model, search, store, saver)
        if mode == "prepare":
            await graph.ainvoke(initial_state(store), config)
            if gate == "material":
                snapshot = await graph.aget_state(config)
                await graph.ainvoke(decision(snapshot.interrupts[0].value), config)
            snapshot = await graph.aget_state(config)
            assert snapshot.next == (f"{gate}_approval",)
            store.write_json("expected_interrupt.json", snapshot.interrupts[0].value)
        else:
            snapshot = await graph.aget_state(config)
            assert snapshot.interrupts[0].value == store.read_json("expected_interrupt.json")
            while snapshot.interrupts:
                await graph.ainvoke(decision(snapshot.interrupts[0].value), config)
                snapshot = await graph.aget_state(config)
            assert snapshot.values["stage"] == "completed"
            assert not snapshot.next
            assert model.calls["Plan"] == 0
            assert model.calls["Report"] == 1
            if gate == "material":
                assert not search.calls
                assert model.calls["Material"] == 0
            store.verify(snapshot.values["report_refs"])
            assert (store.path / "report.md").is_file()
    print(f"{mode} {gate}: OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "finish"])
    parser.add_argument("root", type=Path)
    parser.add_argument("gate", choices=["plan", "material"])
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.root, args.gate))
