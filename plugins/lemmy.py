# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search a Lemmy instance as results.

Hits the public Lemmy ``/api/v3/search`` endpoint (no auth needed on this
instance) and turns matching posts into ordinary results.  Post links point at
the local ``/post/<id>`` page so the discussion is readable on your own instance
even when the community lives elsewhere.

The lookup is prefetched during ``pre_search`` so it overlaps the engine
fan-out (see ``sx_prefetch``).
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from flask_babel import gettext as _  # ty: ignore[unresolved-import]
from searx import settings  # ty: ignore[unresolved-import]
from searx.plugins import Plugin, PluginInfo  # ty: ignore[unresolved-import]
from searx.result_types import MainResult  # ty: ignore[unresolved-import]

from sx_prefetch import Prefetcher

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "base_url": "https://your-lemmy-instance.example",
    "limit": 5,
    "sort": "TopAll",
    "timeout": 6.0,
    "join_timeout": 1.5,
    "cache_ttl": 300,
    "cache_size": 128,
}

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MATH_RE = re.compile(r"^[\d\s+\-*/^().,%]+$|^[a-z]{2,6}\s*\([^)]*\)$")
_WORD_RE = re.compile(r"[^\W_]{3,}", re.UNICODE)


def _cfg() -> dict:
    merged = dict(DEFAULTS)
    merged.update(settings.get("lemmy") or {})
    return merged


def _plain(raw: str) -> str:
    return " ".join(html_lib.unescape(_MD_LINK_RE.sub(r"\1", raw or "")).split())


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _wanted(search) -> bool:
    q = (search.search_query.query or "").strip()
    if len(q) < 3 or q.startswith("!") or not any(ch.isalpha() for ch in q):
        return False
    return not _MATH_RE.match(q)


class LemmySearch(Plugin):
    """Add matching Lemmy posts from the configured instance."""

    id = "lemmy"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        cfg = _cfg()
        self._pf = Prefetcher(ttl=int(cfg["cache_ttl"]), size=int(cfg["cache_size"]))
        self.info = PluginInfo(
            id=self.id,
            name=_("Lemmy"),
            description=_("Searches posts on a Lemmy instance"),
        )

    def _search(self, query: str) -> dict:
        cfg = _cfg()
        base = cfg["base_url"].rstrip("/")
        params = urllib.parse.urlencode(
            {"q": query, "type_": "Posts", "limit": int(cfg["limit"]), "sort": cfg["sort"]}
        )
        req = urllib.request.Request(
            f"{base}/api/v3/search?{params}",
            headers={"Accept": "application/json", "User-Agent": "SearXNG"},
        )
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout"])) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.info("lemmy: search failed: %s", exc)
            return {}

    def _fetch(self, query: str) -> list[dict]:
        data = self._search(query)
        if not data.get("posts"):
            # Lemmy's full-text search is AND-ish; retry with the two longest words.
            words = sorted(set(_WORD_RE.findall(query)), key=len, reverse=True)[:2]
            if len(words) == 2:
                data = self._search(" ".join(words))

        communities: dict = {}
        for entry in data.get("communities") or []:
            community = entry.get("community") or {}
            if community.get("id"):
                communities[community["id"]] = community.get("name") or ""

        base = _cfg()["base_url"].rstrip("/")
        out: list[dict] = []
        seen: set = set()
        for entry in data.get("posts") or []:
            post = entry.get("post") or {}
            pid = post.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            body = _plain(post.get("body") or "") or _plain(post.get("embed_description") or "")
            if len(body) > 400:
                body = body[:397].rstrip() + "…"
            community = communities.get(post.get("community_id"))
            if community:
                body = f"!{community} — {body}" if body else f"!{community}"
            out.append(
                {
                    "url": f"{base}/post/{pid}",
                    "title": post.get("name") or f"post {pid}",
                    "content": body,
                    "published": _parse_date(post.get("published") or ""),
                }
            )
        return out

    # -- hooks ---------------------------------------------------------------

    def pre_search(self, request, search):
        if _wanted(search):
            query = search.search_query.query.strip()
            self._pf.prewarm(query.casefold(), lambda: self._fetch(query))
        return True

    def post_search(self, request, search):
        if not _wanted(search):
            return None
        query = search.search_query.query.strip()
        items = self._pf.get(query.casefold(), _cfg()["join_timeout"]) or []
        return [
            MainResult(
                url=item["url"],
                title=item["title"],
                content=html_lib.escape(item["content"], quote=False),
                publishedDate=item["published"],
            )
            for item in items
        ]
