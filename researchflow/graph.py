"""Workflow topology: register nodes, connect edges and compile the graph."""

from functools import partial

from langgraph.graph import END, START, StateGraph

from researchflow.workflow.dependencies import WorkflowDependencies
from researchflow.workflow.nodes.dispatch_search import dispatch_search_node
from researchflow.workflow.nodes.dispatch_summary import dispatch_summary_node
from researchflow.workflow.nodes.dispatch_write import dispatch_write_node
from researchflow.workflow.nodes.export import export_node
from researchflow.workflow.nodes.material_approval import material_approval_node
from researchflow.workflow.nodes.plan import plan_node
from researchflow.workflow.nodes.plan_approval import plan_approval_node
from researchflow.workflow.nodes.search import search_node
from researchflow.workflow.nodes.summary import summary_node
from researchflow.workflow.nodes.write import write_node
from researchflow.workflow.routes import route_after_material_approval, route_after_plan_approval
from researchflow.workflow.state import State


def build_graph(model, search, store, checkpointer):
    """Build the fixed workflow with per-session resources and persistent checkpoints."""
    deps = WorkflowDependencies(model=model, search=search, store=store)
    graph = StateGraph(State)

    graph.add_node("plan", partial(plan_node, deps=deps))
    graph.add_node("plan_approval", partial(plan_approval_node, deps=deps))
    graph.add_node("dispatch_search", partial(dispatch_search_node, deps=deps))
    graph.add_node("search", partial(search_node, deps=deps))
    graph.add_node("dispatch_summary", partial(dispatch_summary_node, deps=deps))
    graph.add_node("summary", partial(summary_node, deps=deps))
    graph.add_node("material_approval", partial(material_approval_node, deps=deps))
    graph.add_node("dispatch_write", partial(dispatch_write_node, deps=deps))
    graph.add_node("write", partial(write_node, deps=deps))
    graph.add_node("export", partial(export_node, deps=deps))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "plan_approval")
    graph.add_edge("dispatch_search", "search")
    graph.add_edge("search", "dispatch_summary")
    graph.add_edge("dispatch_summary", "summary")
    graph.add_edge("summary", "material_approval")
    graph.add_edge("dispatch_write", "write")
    graph.add_edge("write", "export")
    graph.add_edge("export", END)

    graph.add_conditional_edges(
        "plan_approval",
        route_after_plan_approval,
        {"plan": "plan", "dispatch_search": "dispatch_search"},
    )
    graph.add_conditional_edges(
        "material_approval",
        route_after_material_approval,
        {
            "plan": "plan",
            "dispatch_search": "dispatch_search",
            "dispatch_summary": "dispatch_summary",
            "dispatch_write": "dispatch_write",
        },
    )
    return graph.compile(checkpointer=checkpointer)
