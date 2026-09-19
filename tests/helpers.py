"""Deterministic offline fixtures; all research content is synthetic test data."""

from collections import Counter
from copy import deepcopy

import pymupdf
from langgraph.types import Command

from researchflow.schemas import ChunkNotes, Instruction, Material, Plan, Report, Review, Selection
from researchflow.storage import safe_name

PAPER_ID = "2601.00001"
QUOTE = "Synthetic research evidence for offline workflow testing."
RAW_PAPER = {
    "id": PAPER_ID,
    "title": "Synthetic Test Paper",
    "authors": ["Test Author"],
    "published": "2026-01-01",
    "abstract": QUOTE,
}


class FakeModel:
    name = "offline-test-model"

    def __init__(self):
        self.calls = Counter()
        self.inputs = []
        self.bad_citation = False
        self.bad_selection = False
        self.reject_review = False
        self.bad_quote = False

    async def ask(self, role, instruction, data, schema):
        self.calls[schema.__name__] += 1
        self.inputs.append((schema.__name__, deepcopy(data)))
        if schema is Plan:
            return Plan(
                topic="离线测试",
                focus=["合成数据"],
                queries=["synthetic"],
                candidate_limit=1,
                paper_limit=1,
            )
        if schema is Instruction:
            return Instruction(instruction="执行离线测试任务", expected_output="测试产物")
        if schema is Selection:
            return Selection(
                selected_ids=["unknown" if self.bad_selection else PAPER_ID],
                reasons={PAPER_ID: "测试相关性"},
            )
        if schema is ChunkNotes:
            return ChunkNotes(
                findings=[
                    {
                        "claim": "仅用于离线测试的结论",
                        "quote": "Fabricated quote absent from source."
                        if self.bad_quote
                        else QUOTE,
                    }
                ]
            )
        if schema is Material:
            return Material(summary=f"测试总结 [@{PAPER_ID}]", outline=f"测试提纲 [@{PAPER_ID}]")
        if schema is Review:
            return Review(acceptable=not self.reject_review, comments="离线测试审查")
        if schema is Report:
            cited_id = "unknown" if self.bad_citation else PAPER_ID
            return Report(markdown=f"# 离线测试报告\n\n合成结论 [@{cited_id}]")
        raise AssertionError(f"Unexpected model schema: {schema}")


class FakeSearch:
    def __init__(self, store):
        self.calls = []
        self.failures = 0
        self.rows = [RAW_PAPER]
        stem = safe_name(PAPER_ID, 35) + "_" + safe_name(RAW_PAPER["title"], 90)
        # Exercise real PDF parsing and evidence extraction through the existing PDF cache.
        path = store.resolve(f"papers/{stem}.pdf")
        if path.exists():
            return
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), QUOTE)
            doc.save(path)

    async def search(self, source, query, plan, limit, start=0):
        self.calls.append((source, query, limit, start))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("synthetic search failure")
        return {"papers": deepcopy(self.rows)}


def initial_state(store):
    return {
        "session_id": store.path.name,
        "request": "离线测试任务",
        "stage": "plan",
        "rounds": 0,
        "messages": [],
        "approvals": [],
    }


def decision(payload, action="approve", target="summary", **overrides):
    value = {
        "request_id": payload["request_id"],
        "version": payload["version"],
        "action": action,
        "target": target,
        "feedback": "根据测试反馈修改" if action == "revise" else "",
    }
    value.update(overrides)
    return Command(resume=value)
