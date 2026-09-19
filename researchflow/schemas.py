from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Compatibility for existing imports; the workflow owns its persisted state.
from researchflow.workflow.state import State as State


class Plan(BaseModel):
    topic: str
    date_from: str | None = None
    date_to: str | None = None
    focus: list[str]
    queries: list[str] = Field(min_length=1, max_length=5)
    candidate_limit: int = Field(default=30, ge=1, le=100)
    paper_limit: int = Field(default=10, ge=1, le=20)
    scholar_supplement: bool = False
    language: str = "中文"
    report_requirement: str = "约 3000–5000 中文字；研究方向、方法对比、进展与局限"

    @model_validator(mode="after")
    def validate_limits(self):
        from datetime import date

        dates = [date.fromisoformat(v) if v else None for v in (self.date_from, self.date_to)]
        if dates[0] and dates[1] and dates[0] > dates[1]:
            raise ValueError("日期范围倒置")
        if self.paper_limit > self.candidate_limit:
            raise ValueError("入选数不能大于候选上限")
        return self


class Instruction(BaseModel):
    instruction: str = Field(min_length=1)
    expected_output: str = Field(min_length=1)


class Selection(BaseModel):
    selected_ids: list[str]
    reasons: dict[str, str]


class Finding(BaseModel):
    claim: str
    quote: str = Field(min_length=1)


class ChunkNotes(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Material(BaseModel):
    summary: str
    outline: str


class Review(BaseModel):
    acceptable: bool
    comments: str


class Report(BaseModel):
    markdown: str


class Decision(BaseModel):
    request_id: str
    version: int
    action: Literal["approve", "revise"]
    feedback: str = ""
    target: Literal["plan", "search", "summary"] = "plan"

    @model_validator(mode="after")
    def require_feedback(self):
        if self.action == "revise" and not self.feedback.strip():
            raise ValueError("修改必须填写反馈")
        return self
