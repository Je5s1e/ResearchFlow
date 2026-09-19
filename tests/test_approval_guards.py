"""Check approval guards independently of graph routing, with real artifact hashes."""

import tempfile
import unittest
from copy import deepcopy

from researchflow.storage import Store, digest
from researchflow.workflow.approvals import require_approval
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.nodes.export import export_node
from researchflow.workflow.nodes.search import search_node
from researchflow.workflow.nodes.write import write_node
from tests.helpers import FakeModel, FakeSearch


class ApprovalGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="researchflow-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(self.temp.name, "离线审批校验")
        plan_ref, _ = self.store.artifact("plan", "json", "{}")
        material_ref, _ = self.store.artifact("material", "json", "{}")
        self.state = {
            "plan_refs": [plan_ref],
            "plan_request_id": "plan-request",
            "plan_version": 1,
            "material_refs": [plan_ref, material_ref],
            "material_request_id": "material-request",
            "material_version": 1,
            "material": {"plan_version": 1},
            "approvals": [],
        }
        for gate in ("plan", "material"):
            self.state["approvals"].append(
                {
                    "gate": gate,
                    "request_id": self.state[f"{gate}_request_id"],
                    "version": 1,
                    "hash": digest(self.state[f"{gate}_refs"]),
                }
            )

    async def test_valid_approval_chain(self):
        require_approval(self.state, "material", self.store)

    async def test_mismatched_approval_identity_version_or_hash(self):
        for field, value in (("request_id", "old"), ("version", 0), ("hash", "wrong")):
            with self.subTest(field=field):
                state = deepcopy(self.state)
                state["approvals"][0][field] = value
                with self.assertRaisesRegex(ValueError, "plan 未获得当前版本审批"):
                    require_approval(state, "plan", self.store)

    async def test_material_requires_upstream_plan_approval(self):
        self.state["approvals"] = self.state["approvals"][1:]
        with self.assertRaisesRegex(ValueError, "plan 未获得当前版本审批"):
            require_approval(self.state, "material", self.store)

    async def test_material_cannot_refer_to_old_plan(self):
        self.state["material"]["plan_version"] = 0
        with self.assertRaisesRegex(ValueError, "材料不是基于当前计划生成"):
            require_approval(self.state, "material", self.store)

    async def test_changed_artifact_after_approval_is_rejected(self):
        self.store.resolve(self.state["material_refs"][-1]["path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "产物缺失或被修改"):
            require_approval(self.state, "material", self.store)

    async def test_execution_nodes_enforce_approval_without_router(self):
        self.state["approvals"] = []
        model, search = FakeModel(), FakeSearch(self.store)
        deps = WorkflowDependencies(model=model, search=search, store=self.store)
        for node in (search_node, write_node):
            with self.subTest(node=node.__name__):
                with self.assertRaisesRegex(ValueError, "未获得当前版本审批"):
                    await node(self.state, deps=deps)
        with self.assertRaisesRegex(ValueError, "未获得当前版本审批"):
            export_node(self.state, deps=deps)
        self.assertFalse(model.calls)
        self.assertFalse(search.calls)
        self.assertFalse((self.store.path / "report.md").exists())
