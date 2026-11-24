"""Tavily search API engine."""

import typing as t

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://tavily.com",
    "wikidata_id": None,
    "official_api_documentation": "https://docs.tavily.com/documentation/api-reference/endpoint/search",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
"""API key for the Tavily API (required)."""

categories = ["general", "web"]
paging = False

base_url = "https://api.tavily.com/search"
results_per_page: int = 10
search_depth: str = "basic"


def request(query: str, params: "OnlineParams") -> None:
    params["method"] = "POST"
    params["url"] = base_url
    params["headers"]["Authorization"] = f"Bearer {api_key}"
    params["headers"]["Content-Type"] = "application/json"
    params["json"] = {
        "query": query,
        "max_results": results_per_page,
        "search_depth": search_depth,
        "include_answer": False,
        "include_images": False,
    }


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    for item in resp.json().get("results") or []:
        url = item.get("url")
        if not url:
            continue
        res.add(
            res.types.MainResult(
                url=url,
                title=item.get("title") or url,
                content=item.get("content") or "",
            )
        )
    return res
