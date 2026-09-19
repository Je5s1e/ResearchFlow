from researchflow.storage import atomic_write
from researchflow.tools.papers import bibliography, citations_valid
from researchflow.workflow.approvals import require_approval
from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.state import State


def export_node(state: State, *, deps: WorkflowDependencies) -> dict:
    """Validate approved inputs and export the final Markdown and bibliography."""
    store = deps.store
    require_approval(state, "material", store)
    report = state["report"]
    citations_valid(report["markdown"], state["material"]["cited_ids"])
    papers = [p for p in state["material"]["papers"] if p["id"] in report["cited_ids"]]
    md = (
        report["markdown"]
        + "\n\n## 参考文献\n\n"
        + "\n".join(
            f"- [@{p['id']}] {p['title']}. {', '.join(p['authors'])}. {p.get('published') or p.get('year') or '日期未知'}. {p['url']}"
            for p in papers
        )
        + "\n"
    )
    ref, _ = store.artifact("05_调研报告", "md", md)
    bib, _ = store.artifact("06_参考文献", "bib", bibliography(papers))
    atomic_write(store.path / "report.md", md)
    return {"stage": "completed", "report_refs": [ref, bib]}
