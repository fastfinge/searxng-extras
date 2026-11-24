"""You.com search API engine."""

import typing as t
from urllib.parse import urlencode

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://you.com",
    "wikidata_id": None,
    "official_api_documentation": "https://docs.you.com/api-reference/search",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
"""API key for the You.com search API (required)."""

categories = ["other"]
paging = False

base_url = "https://api.you.com/v1/search"
results_per_page: int = 10

# you.com sits behind Cloudflare and rejects non-browser user agents
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def request(query: str, params: "OnlineParams") -> None:
    params["method"] = "GET"
    params["url"] = base_url + "?" + urlencode({"query": query, "count": results_per_page})
    params["headers"]["X-API-Key"] = api_key
    params["headers"]["User-Agent"] = _USER_AGENT
    params["headers"]["Accept"] = "application/json"


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    for item in (resp.json().get("results") or {}).get("web") or []:
        url = item.get("url")
        if not url:
            continue
        snippets = item.get("snippets") or []
        res.add(
            res.types.MainResult(
                url=url,
                title=item.get("title") or url,
                content=item.get("description") or (" ".join(snippets) if snippets else ""),
            )
        )
    return res
