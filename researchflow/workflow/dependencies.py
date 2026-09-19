"""Runtime resources bound to nodes, never serialized into checkpoint state."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from researchflow.agents.model import Model
    from researchflow.storage import Store
    from researchflow.tools.mcp_client import SearchMCP


@dataclass(frozen=True)
class WorkflowDependencies:
    model: "Model"
    search: "SearchMCP"
    store: "Store"
