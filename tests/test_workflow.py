"""Integration tests using real LangGraph, SQLite, Store and PDF evidence processing."""

import tempfile
import unittest
from contextlib import AsyncExitStack
from copy import deepcopy
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from researchflow.graph import build_graph
from researchflow.storage import Store
from tests.helpers import PAPER_ID, FakeModel, FakeSearch, decision, initial_state


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="researchflow-test-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(self.temp.name, "离线测试")
        self.model = FakeModel()
        self.search = FakeSearch(self.store)
        self.config = {"configurable": {"thread_id": self.store.path.name}, "recursion_limit": 150}
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        await self.reopen()

    async def reopen(self):
        await self.stack.aclose()
        self.saver = await self.stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(self.store.path / "checkpoints.sqlite"))
        )
        self.graph = build_graph(self.model, self.search, self.store, self.saver)

    async def start(self):
        await self.graph.ainvoke(initial_state(self.store), self.config)
        return await self.snapshot()

    async def snapshot(self):
        return await self.graph.aget_state(self.config)

    async def respond(self, action="approve", target="summary", **overrides):
        snapshot = await self.snapshot()
        self.assertEqual(len(snapshot.interrupts), 1)
        command = decision(snapshot.interrupts[0].value, action, target, **overrides)
        await self.graph.ainvoke(command, self.config)
        return await self.snapshot()

    async def material_gate(self):
        await self.start()
        return await self.respond()

    async def test_full_flow_pauses_at_both_gates_and_exports(self):
        plan = await self.start()
        self.assertEqual(plan.next, ("plan_approval",))
        self.assertEqual(self.search.calls, [])
        self.assertEqual(self.model.calls["Report"], 0)
        material = await self.respond()
        self.assertEqual(material.next, ("material_approval",))
        self.assertEqual(material.values["evidence"][0]["read_scope"], "full_text")
        self.assertEqual(material.values["evidence"][0]["findings"][0]["page"], 1)
        self.assertEqual(self.model.calls["Report"], 0)
        self.assertFalse((self.store.path / "report.md").exists())
        completed = await self.respond()
        self.assertFalse(completed.next)
        self.assertEqual(completed.values["stage"], "completed")
        self.assertEqual({a["gate"] for a in completed.values["approvals"]}, {"plan", "material"})
        self.assertEqual(self.model.calls["Report"], 1)
        self.store.verify(completed.values["report_refs"])
        report = (self.store.path / "report.md").read_text()
        self.assertIn(f"[@{PAPER_ID}]", report)
        self.assertIn("## 参考文献", report)
        bib = next(r for r in completed.values["report_refs"] if r["path"].endswith(".bib"))
        self.assertIn(f"@misc{{{PAPER_ID}", self.store.resolve(bib["path"]).read_text())
        # A completed checkpoint resumed without new input must not write again.
        await self.graph.ainvoke(None, self.config)
        self.assertEqual(self.model.calls["Report"], 1)

    async def test_plan_revision_requires_fresh_approval(self):
        old = await self.start()
        revised = await self.respond("revise", "plan")
        self.assertEqual(revised.next, ("plan_approval",))
        self.assertGreater(revised.values["plan_version"], old.values["plan_version"])
        self.assertNotEqual(revised.values["plan_request_id"], old.values["plan_request_id"])
        self.assertEqual(revised.values["approvals"], [])
        self.assertEqual(self.search.calls, [])
        self.assertEqual(revised.values["rounds"], 1)
        self.assertEqual(self.model.inputs[-1][1]["feedback"], "根据测试反馈修改")
        with self.assertRaisesRegex(ValueError, "审批请求或版本已失效"):
            await self.graph.ainvoke(decision(old.interrupts[0].value), self.config)
        self.assertEqual(self.search.calls, [])

    async def test_summary_revision_reuses_search_but_needs_material_approval(self):
        old = await self.material_gate()
        search_count = len(self.search.calls)
        revised = await self.respond("revise", "summary")
        self.assertEqual(revised.next, ("material_approval",))
        self.assertEqual(len(self.search.calls), search_count)
        self.assertGreater(revised.values["material_version"], old.values["material_version"])
        self.assertEqual([a["gate"] for a in revised.values["approvals"]], ["plan"])
        self.assertEqual(self.model.calls["Report"], 0)
        completed = await self.respond()
        self.assertEqual(completed.values["stage"], "completed")

    async def test_search_revision_advances_search_round(self):
        old = await self.material_gate()
        revised = await self.respond("revise", "search")
        self.assertEqual(revised.next, ("material_approval",))
        self.assertEqual(revised.values["search_round"], old.values["search_round"] + 1)
        self.assertEqual([call[3] for call in self.search.calls], [0, 1])
        self.assertEqual(self.model.calls["Report"], 0)
        self.assertEqual((await self.respond()).values["stage"], "completed")

    async def test_material_revision_to_plan_invalidates_downstream(self):
        old = await self.material_gate()
        revised = await self.respond("revise", "plan")
        self.assertEqual(revised.next, ("plan_approval",))
        self.assertGreater(revised.values["plan_version"], old.values["plan_version"])
        for key in (
            "approvals",
            "papers",
            "evidence",
            "material_refs",
            "search_refs",
            "report_refs",
        ):
            self.assertEqual(revised.values[key], [])
        self.assertEqual(revised.values["material"], {})
        self.assertEqual(revised.values["search_round"], 0)
        self.assertEqual((await self.respond()).next, ("material_approval",))
        self.assertEqual((await self.respond()).values["stage"], "completed")

    async def test_wrong_request_is_rejected_before_search(self):
        await self.start()
        with self.assertRaisesRegex(ValueError, "审批请求或版本已失效"):
            await self.respond(request_id="stale")
        self.assertEqual(self.search.calls, [])

    async def test_wrong_version_is_rejected_before_search(self):
        await self.start()
        with self.assertRaisesRegex(ValueError, "审批请求或版本已失效"):
            await self.respond(version=999)
        self.assertEqual(self.search.calls, [])

    async def test_tampered_plan_is_rejected(self):
        snapshot = await self.start()
        self.store.resolve(snapshot.values["plan_refs"][0]["path"]).write_text("tampered")
        with self.assertRaisesRegex(ValueError, "产物缺失或被修改"):
            await self.respond()
        self.assertEqual(self.search.calls, [])

    async def test_missing_material_file_is_rejected(self):
        snapshot = await self.material_gate()
        self.store.resolve(snapshot.values["material_refs"][-1]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "产物缺失或被修改"):
            await self.respond()
        self.assertEqual(self.model.calls["Report"], 0)

    async def test_sqlite_reopen_preserves_both_interrupts(self):
        before = await self.start()
        await self.reopen()
        after = await self.snapshot()
        self.assertEqual(before.interrupts[0].value, after.interrupts[0].value)
        self.assertEqual(self.model.calls["Plan"], 1)
        material = await self.respond()
        counts = deepcopy(self.model.calls)
        await self.reopen()
        self.assertEqual(material.interrupts[0].value, (await self.snapshot()).interrupts[0].value)
        completed = await self.respond()
        self.assertEqual(completed.values["stage"], "completed")
        self.assertEqual(self.model.calls["Plan"], counts["Plan"])
        self.assertEqual(self.model.calls["Material"], counts["Material"])

    async def test_search_failure_can_retry_from_checkpoint(self):
        await self.start()
        self.search.failures = 1
        with self.assertRaisesRegex(RuntimeError, "synthetic search failure"):
            await self.respond()
        self.assertEqual((await self.snapshot()).next, ("search",))
        await self.reopen()
        await self.graph.ainvoke(None, self.config)
        self.assertEqual((await self.snapshot()).next, ("material_approval",))
        self.assertEqual(self.model.calls["Plan"], 1)
        self.assertEqual((await self.respond()).values["stage"], "completed")

    async def test_invalid_selection_blocks_summary(self):
        await self.start()
        self.model.bad_selection = True
        with self.assertRaisesRegex(ValueError, "无效论文选择"):
            await self.respond()
        self.assertEqual(self.model.calls["Material"], 0)

    async def test_unmatched_quotes_cannot_support_summary(self):
        await self.start()
        self.model.bad_quote = True
        with self.assertRaisesRegex(ValueError, "没有可支持总结"):
            await self.respond()
        self.assertEqual(self.model.calls["Material"], 0)

    async def test_rejected_review_cannot_reach_material_approval(self):
        await self.start()
        self.model.reject_review = True
        with self.assertRaisesRegex(ValueError, "材料检查未通过"):
            await self.respond()
        self.assertFalse((await self.snapshot()).interrupts)
        self.assertEqual(self.model.calls["Report"], 0)

    async def test_unknown_report_citation_blocks_export_and_can_retry(self):
        await self.material_gate()
        self.model.bad_citation = True
        with self.assertRaisesRegex(ValueError, "引用不在批准证据中"):
            await self.respond()
        self.assertFalse((self.store.path / "report.md").exists())
        self.model.bad_citation = False
        await self.reopen()
        await self.graph.ainvoke(None, self.config)
        self.assertEqual((await self.snapshot()).values["stage"], "completed")

    async def test_revision_limit(self):
        await self.start()
        for _ in range(10):
            await self.respond("revise", "plan")
        with self.assertRaisesRegex(ValueError, "超过10轮"):
            await self.respond("revise", "plan")
        self.assertEqual(self.search.calls, [])

    async def test_session_outputs_stay_in_temporary_directory(self):
        await self.material_gate()
        await self.respond()
        self.assertTrue(self.store.path.is_relative_to(Path(self.temp.name).resolve()))
        for path in self.store.path.rglob("*"):
            self.assertTrue(path.resolve().is_relative_to(Path(self.temp.name).resolve()))
