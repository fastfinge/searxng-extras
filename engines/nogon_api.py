"""Nogon browsing-history engine (self-hosted)."""

import typing as t
from urllib.parse import urlencode

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://nogon.eu",
    "wikidata_id": None,
    "official_api_documentation": "https://nogon.eu/docs/developer",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

access_token: str = ""
"""Nogon app.access_token (required, the instance is not in public mode)."""

enable_http = True
"""Nogon lives on the nebula mesh over plain HTTP; SearXNG defaults to https-only."""

categories = ["general"]
search_url = "http://127.0.0.1:4433/search"
"""Nogon base URL; override per engine in settings.yml (see settings-example.yml)."""
results_per_page: int = 20
paging = False


def request(query: str, params: "OnlineParams") -> None:
    qs = urlencode(
        {
            "q": query,
            "format": "json",
            "semantic": 1,
            "limit": results_per_page,
        }
    )
    params["method"] = "GET"
    params["url"] = f"{search_url}?{qs}"
    params["headers"]["X-Access-Token"] = access_token


def _add(res: EngineResults, item: dict, content: str = "") -> None:
    url = item.get("url")
    if not url:
        return
    meta = item.get("metadata") or {}
    content = content or meta.get("description") or item.get("text") or ""
    res.add(
        res.types.MainResult(
            url=url,
            title=item.get("title") or url,
            content=content[:500],
        )
    )


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    data = resp.json()
    seen = set()

    for item in data.get("documents") or []:
        if item.get("url") not in seen:
            seen.add(item.get("url"))
            _add(res, item)

    # Pure vector matches come back separately from the lexical hits.
    for hit in data.get("semantic_hits") or []:
        doc = hit.get("document") or {}
        url = doc.get("url") or hit.get("doc_id")
        if not url or url in seen:
            continue
        seen.add(url)
        _add(res, doc, content=hit.get("matched_chunk") or "")

    return res
