import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("researchflow-arxiv")
NS = {"a": "http://www.w3.org/2005/Atom"}

@mcp.tool()
def search_papers(query: str, max_results: int = 5, start: int = 0, abstract_mode: str = "full", date_from: str | None = None, date_to: str | None = None) -> dict:
    terms = query.strip()
    if date_from or date_to:
        lo = (date_from or "19910701").replace("-", "") + "0000"
        hi = (date_to or "20991231").replace("-", "") + "2359"
        terms += f" AND submittedDate:[{lo} TO {hi}]"
    params = urllib.parse.urlencode({"search_query": terms, "start": max(0, int(start)), "max_results": min(50, int(max_results))})
    req = urllib.request.Request("https://export.arxiv.org/api/query?" + params, headers={"User-Agent": "ResearchFlow/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            root = ET.fromstring(response.read())
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    papers = []
    for entry in root.findall("a:entry", NS):
        ident = (entry.findtext("a:id", "", NS)).rsplit("/", 1)[-1]
        title = " ".join((entry.findtext("a:title", "", NS)).split())
        abstract = " ".join((entry.findtext("a:summary", "", NS)).split())
        authors = [x.findtext("a:name", "", NS) for x in entry.findall("a:author", NS)]
        published = entry.findtext("a:published", "", NS)[:10]
        papers.append({"id": ident, "title": title, "authors": authors, "published": published, "abstract": abstract, "url": f"https://arxiv.org/abs/{ident}", "pdf_url": f"https://arxiv.org/pdf/{ident}.pdf"})
    return {"status": "ok", "papers": papers}

if __name__ == "__main__":
    mcp.run(transport="stdio")
