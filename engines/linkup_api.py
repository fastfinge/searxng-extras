"""Linkup search API engine."""

import typing as t

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://linkup.so",
    "wikidata_id": None,
    "official_api_documentation": "https://docs.linkup.so/pages/documentation/api-reference/search",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
"""API key for the Linkup API (required)."""

categories = ["other"]
paging = False

base_url = "https://api.linkup.so/v1/search"
results_per_page: int = 20
depth: str = "standard"


def request(query: str, params: "OnlineParams") -> None:
    params["method"] = "POST"
    params["url"] = base_url
    params["headers"]["Authorization"] = f"Bearer {api_key}"
    params["headers"]["Content-Type"] = "application/json"
    params["json"] = {
        "q": query,
        "depth": depth,
        "outputType": "searchResults",
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
                title=item.get("name") or url,
                content=item.get("content") or "",
            )
        )
    return res
