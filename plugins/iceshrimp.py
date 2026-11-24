# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search a local Iceshrimp/Mastodon instance as results.

Uses the Mastodon-compatible ``/api/v2/search`` endpoint with a read-scoped
token minted for this plugin (OAuth app "SearXNG search", token in the
container env as ``ICESHRIMP_TOKEN``).  Statuses are added as ordinary results.

The lookup is prefetched during ``pre_search`` so it overlaps the engine
fan-out (see ``sx_prefetch``).
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import os
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
    "base_url": "https://your-iceshrimp-instance.example",
    "limit": 5,
    "timeout": 6.0,
    "join_timeout": 1.5,
    "cache_ttl": 300,
    "cache_size": 128,
}

_TAG_RE = re.compile(r"<[^>]+>")


def _cfg() -> dict:
    merged = dict(DEFAULTS)
    merged.update(settings.get("iceshrimp") or {})
    return merged


def _plain(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    return " ".join(html_lib.unescape(text).split())


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


_MATH_RE = re.compile(r"^[\d\s+\-*/^().,%]+$|^[a-z]{2,6}\s*\([^)]*\)$")


def _wanted(search) -> bool:
    q = (search.search_query.query or "").strip()
    if len(q) < 3 or q.startswith("!") or not any(ch.isalpha() for ch in q):
        return False
    if _MATH_RE.match(q):
        return False
    cats = search.search_query.categories or []
    return not cats or "general" in cats


class IceshrimpSearch(Plugin):
    """Add matching statuses from the configured instance."""

    id = "iceshrimp"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        cfg = _cfg()
        self._pf = Prefetcher(ttl=int(cfg["cache_ttl"]), size=int(cfg["cache_size"]))
        self.info = PluginInfo(
            id=self.id,
            name=_("Iceshrimp"),
            description=_("Searches a fediverse instance"),
        )

    def _search(self, query: str) -> list[dict]:
        token = os.environ.get("ICESHRIMP_TOKEN", "")
        if not token:
            logger.warning("iceshrimp: ICESHRIMP_TOKEN is not set")
            return []

        cfg = _cfg()
        params = urllib.parse.urlencode(
            {"q": query, "type": "statuses", "limit": int(cfg["limit"]), "resolve": "false"}
        )
        req = urllib.request.Request(
            f"{cfg['base_url'].rstrip('/')}/api/v2/search?{params}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout"])) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.info("iceshrimp: search failed: %s", exc)
            return []
        return data.get("statuses") or []

    def _fetch(self, query: str) -> list[dict]:
        statuses = self._search(query)
        if not statuses:
            # Mastodon search is AND-ish; retry with the two longest words.
            words = sorted(set(re.findall(r"[^\W_]{3,}", query)), key=len, reverse=True)[:2]
            if len(words) == 2 and " ".join(words) != query:
                statuses = self._search(" ".join(words))

        out: list[dict] = []
        seen: set[str] = set()
        for status in statuses:
            status = status.get("reblog") or status
            link = status.get("url") or status.get("uri")
            if not link or link in seen:
                continue
            seen.add(link)
            account = status.get("account") or {}
            author = account.get("display_name") or account.get("acct") or "unknown"
            handle = account.get("acct") or ""
            body = _plain(status.get("content") or "")
            spoiler = _plain(status.get("spoiler_text") or "")
            if spoiler:
                body = f"{spoiler} — {body}" if body else spoiler
            if len(body) > 400:
                body = body[:397].rstrip() + "…"
            out.append(
                {
                    "url": link,
                    "title": author + (f" (@{handle})" if handle else ""),
                    "content": body,
                    "published": _parse_date(status.get("created_at") or ""),
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
