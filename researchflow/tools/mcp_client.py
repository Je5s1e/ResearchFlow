import asyncio
import json
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from researchflow.config import ROOT
from researchflow.storage import digest, now


class SearchMCP:
    def __init__(self, store):
        self.store = store
        self.last_call = 0.0
        self.config = json.loads((ROOT / "mcp.json").read_text())

    async def call(self, server, name=None, arguments=None):
        spec = self.config[server]
        values = {"session_dir": str(self.store.path), "python": sys.executable}
        params = StdioServerParameters(
            command=spec["command"].format(**values),
            args=[a.format(**values) for a in spec["args"]],
        )
        with (self.store.path / f"logs/mcp/{server}.stderr.log").open("a") as err:
            async with asyncio.timeout(90):
                async with stdio_client(params, errlog=err) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        if name is None:
                            return [
                                t.model_dump(mode="json")
                                for t in (await session.list_tools()).tools
                            ]
                        result = await session.call_tool(name, arguments or {})
        if result.isError:
            raise RuntimeError(f"{server} MCP tool failed: {result.content}")
        if result.structuredContent:
            return result.structuredContent
        blocks = [c.text for c in result.content if c.type == "text"]
        if len(blocks) != 1:
            raise ValueError(f"{server}: expected one JSON result")
        return json.loads(blocks[0])

    async def search(self, source, query, plan, limit, start=0):
        args = {"query": query}
        if start:
            args["start"] = start
        if source == "arxiv":
            tool = "search_papers"
            args.update(max_results=min(limit, 50), abstract_mode="full")
            for key in ("date_from", "date_to"):
                if plan.get(key):
                    args[key] = plan[key]
        else:
            tool = "search_google_scholar"
            args["num_results"] = min(limit, 20)
            for field, target in (("date_from", "year_from"), ("date_to", "year_to")):
                if plan.get(field):
                    args[target] = int(plan[field][:4])
        cache = f"logs/mcp/{source}-{digest(args)[:20]}.json"
        if self.store.resolve(cache).exists():
            return self.store.read_json(cache)["result"]
        for attempt in range(3):
            try:
                await asyncio.sleep(max(0, 3 - (time.monotonic() - self.last_call)))
                self.last_call = time.monotonic()
                data = await self.call(source, tool, args)
                if (
                    not isinstance(data, dict)
                    or "papers" not in data
                    or data.get("status") in ("error", "rate_limited")
                ):
                    raise RuntimeError(f"{source} 检索失败：{data}")
                self.store.write_json(
                    cache, {"time": now(), "tool": tool, "args": args, "result": data}
                )
                self.store.event(
                    "tool", {"server": source, "tool": tool, "args": args, "file": cache}
                )
                return data
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(3 * (attempt + 1))
