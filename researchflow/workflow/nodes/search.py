from researchflow.schemas import Selection
from researchflow.storage import json_text
from researchflow.tools.papers import deduplicate, evidence, normalize
from researchflow.workflow.approvals import require_approval
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.messages import result_message
from researchflow.workflow.state import State


async def search_node(state: State, *, deps: WorkflowDependencies) -> dict:
    """Retrieve and select papers, extract evidence and persist search artifacts."""
    model, search, store = deps.model, deps.search, deps.store
    require_approval(state, "plan", store)
    p = state["plan"]
    papers = []
    arxiv_budget = (
        max(p["paper_limit"], p["candidate_limit"] * 2 // 3)
        if p["scholar_supplement"]
        else p["candidate_limit"]
    )
    per_query = max(1, arxiv_budget // len(p["queries"]))
    for query in p["queries"]:
        remaining = arxiv_budget - len(papers)
        if remaining <= 0:
            break
        data = await search.search(
            "arxiv", query, p, min(per_query, remaining), state.get("search_round", 0) * per_query
        )
        papers.extend(normalize(row, "arxiv") for row in data["papers"])
    papers = deduplicate(papers)
    warnings = []
    if p["scholar_supplement"] or len(papers) < p["paper_limit"]:
        for query in p["queries"]:
            remaining = p["candidate_limit"] - len(papers)
            if remaining <= 0:
                break
            try:
                data = await search.search(
                    "scholar",
                    query,
                    p,
                    remaining,
                    state.get("search_round", 0) * min(remaining, 20),
                )
                papers = deduplicate(papers + [normalize(row, "scholar") for row in data["papers"]])
            except Exception as exc:
                warnings.append(f"Scholar 补充失败：{type(exc).__name__}")
                store.event("warning", {"message": warnings[-1]})
                break
    for paper in papers:
        published = (paper.get("published") or "")[:10]
        paper["date_status"] = "unverified"
        if published:
            paper["date_status"] = (
                "within_range"
                if (
                    (not p["date_from"] or published >= p["date_from"])
                    and (not p["date_to"] or published <= p["date_to"])
                )
                else "outside_range"
            )
    papers = [x for x in papers if x["date_status"] != "outside_range"][: p["candidate_limit"]]
    if not papers:
        raise ValueError("没有候选论文，请修改计划或重试")
    allowed = {x["id"] for x in papers}
    feedback = ""
    for attempt in range(3):
        selection = await model.ask(
            "检索 Agent",
            "按任务相关性筛选论文。只能使用候选 id，不超过 paper_limit。允许的 id："
            + ", ".join(sorted(allowed))
            + "。为每篇候选给出入选/排除理由。"
            + (" 上次选择无效，请纠正：" + feedback if feedback else ""),
            {"task": state["task"], "plan": p, "candidates": papers, "feedback": feedback},
            Selection,
        )
        ids = selection.selected_ids
        if ids and len(ids) == len(set(ids)) and len(ids) <= p["paper_limit"] and set(ids) <= allowed:
            break
        feedback = "选择必须非空、无重复、数量不超过限制，且只能使用候选 id。"
        if attempt == 2:
            raise ValueError("检索 Agent 返回无效论文选择")
    for paper in papers:
        paper.update(
            selected=paper["id"] in ids, reason=selection.reasons.get(paper["id"], "未提供理由")
        )
    notes = []
    for paper in papers:
        if paper["selected"]:
            store.event("progress", {"message": f"读取 {paper['title']}"})
            notes.append(await evidence(paper, model, store))
    listing = {"papers": papers, "warnings": warnings, "selected_count": len(ids)}
    ref, _ = store.artifact("02_论文清单", "json", json_text(listing))
    md = (
        "# 论文清单\n\n"
        + "\n".join(warnings)
        + "\n\n"
        + "\n\n".join(
            f"- {'入选' if x['selected'] else '排除'}：[{x['title']}]({x['url']}) — {x['reason']}"
            for x in papers
        )
    )
    mdref, _ = store.artifact("02_论文清单", "md", md)
    refs = [ref, mdref] + [r for note in notes for r in note["refs"]]
    return {
        "papers": papers,
        "evidence": notes,
        "search_refs": refs,
        "search_round": state.get("search_round", 0) + 1,
        "messages": result_message(
            state, "检索 Agent", f"检索完成：{len(papers)} 篇候选，{len(ids)} 篇入选。", refs
        ),
    }
