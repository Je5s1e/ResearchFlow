import re

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("researchflow-scholar")


@mcp.tool()
async def search_google_scholar(
    query: str,
    num_results: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    start: int = 0,
) -> dict:
    params = {"q": query, "num": min(max(num_results, 1), 20), "hl": "en"}
    params["start"] = max(0, start)
    if year_from:
        params["as_ylo"] = year_from
    if year_to:
        params["as_yhi"] = year_to
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        response = await client.get(
            "https://scholar.google.com/scholar",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    if soup.select_one("#gs_captcha_f, .g-recaptcha") or "/sorry/" in str(response.url):
        raise RuntimeError("Google Scholar requires verification")
    rows = soup.select(".gs_r.gs_or.gs_scl")
    if not rows and not soup.select_one("#gs_res_ccl"):
        raise RuntimeError("Unrecognized Google Scholar response")
    papers = []
    for row in rows[:num_results]:
        title = row.select_one(".gs_rt")
        link = row.select_one(".gs_rt a")
        author = row.select_one(".gs_a")
        snippet = row.select_one(".gs_rs")
        pdf = row.select_one(".gs_or_ggsm a")
        author_text = author.get_text(" ", strip=True) if author else ""
        year = re.search(r"\b(?:19|20)\d{2}\b", author_text)
        if title:
            papers.append(
                {
                    "title": title.get_text(" ", strip=True),
                    "authors": [author_text],
                    "year": year.group() if year else None,
                    "url": link.get("href", "") if link else "",
                    "pdf_url": pdf.get("href") if pdf and "PDF" in pdf.get_text() else None,
                    "abstract": snippet.get_text(" ", strip=True) if snippet else "",
                    "read_scope": "search_snippet",
                    "source": "scholar",
                }
            )
    return {"papers": papers}


if __name__ == "__main__":
    mcp.run(transport="stdio")
