"""Serper.dev Google Search API engine."""

import typing as t

from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams

about = {
    "website": "https://serper.dev",
    "wikidata_id": None,
    "official_api_documentation": "https://serper.dev/playground",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

api_key: str = ""
"""API key for serper.dev (required)."""

categories = ["general", "web"]
paging = False
time_range_support = True

base_url = "https://google.serper.dev/search"
results_per_page: int = 20

_TIME_RANGE = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}


def request(query: str, params: "OnlineParams") -> None:
    body: dict[str, t.Any] = {"q": query, "num": results_per_page}

    locale = (params.get("searxng_locale") or "").split("-")
    body["hl"] = locale[0] or "en"
    if len(locale) > 1 and locale[1]:
        body["gl"] = locale[1].lower()

    time_range = params.get("time_range")
    if time_range in _TIME_RANGE:
        body["tbs"] = _TIME_RANGE[time_range]

    params["method"] = "POST"
    params["url"] = base_url
    params["headers"]["X-API-KEY"] = api_key
    params["headers"]["Content-Type"] = "application/json"
    params["json"] = body


def response(resp: "SXNG_Response") -> EngineResults:
    res = EngineResults()
    for item in resp.json().get("organic") or []:
        url = item.get("link")
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
