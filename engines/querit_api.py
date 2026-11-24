"""Querit.ai search API engine."""

import typing as t

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://www.querit.ai",
    "wikidata_id": None,
    "official_api_documentation": "https://www.querit.ai/en/docs",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
"""API key for the Querit.ai search API (required)."""

categories = ["other"]
paging = False

base_url = "https://api.querit.ai/v1/search"
results_per_page: int = 10


def request(query: str, params: "OnlineParams") -> None:
    params["method"] = "POST"
    params["url"] = base_url
    params["headers"]["Authorization"] = f"Bearer {api_key}"
    params["headers"]["Content-Type"] = "application/json"
    params["json"] = {"query": query, "count": results_per_page}


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    payload = resp.json().get("results") or {}
    for item in payload.get("result") or []:
        url = item.get("url")
        if not url:
            continue
        res.add(
            res.types.MainResult(
                url=url,
                title=item.get("title") or url,
                content=item.get("snippet") or "",
            )
        )
    return res
