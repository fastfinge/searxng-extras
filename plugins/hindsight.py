# SPDX-License-Identifier: AGPL-3.0-or-later
"""Surface Hindsight memories that relate to the current search.

Recalls from the ``hermes`` bank on the Hindsight API (giant, over nebula) and
adds the best matches as *answer* blocks above the web results, so a search
shows what Sam already knows before it shows the web.

The recall is started in ``pre_search`` and joined in ``post_search`` (see
``sx_prefetch``), so its 1.5-3.5 s overlaps the engine fan-out instead of adding
to it.  Fail-open everywhere: no key, a timeout, or a bad response just means no
memory block, never a broken search.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from flask_babel import gettext as _  # ty: ignore[unresolved-import]
from searx import settings  # ty: ignore[unresolved-import]
from searx.plugins import Plugin, PluginInfo  # ty: ignore[unresolved-import]
from searx.result_types import Answer  # ty: ignore[unresolved-import]

from sx_prefetch import Prefetcher

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "url": "http://127.0.0.1:9177",
    "bank": "hermes",
    "budget": "low",
    "max_tokens": 800,
    "max_results": 5,
    "types": [],
    "timeout": 8.0,
    "join_timeout": 2.5,
    "min_semantic": 0.62,
    "cache_ttl": 900,
    "cache_size": 256,
}


def _cfg() -> dict:
    merged = dict(DEFAULTS)
    merged.update(settings.get("hindsight") or {})
    return merged


_MATH_RE = re.compile(r"^[\d\s+\-*/^().,%]+$|^[a-z]{2,6}\s*\([^)]*\)$")


def _wanted(search) -> bool:
    q = (search.search_query.query or "").strip()
    if len(q) < 3 or q.startswith("!") or not any(ch.isalpha() for ch in q):
        return False
    if _MATH_RE.match(q):
        return False
    cats = search.search_query.categories or []
    return not cats or "general" in cats


class HindsightMemory(Plugin):
    """Add Hindsight memories related to the query as answer blocks."""

    id = "hindsight"

    def __init__(self, plg_cfg):
        super().__init__(plg_cfg)
        cfg = _cfg()
        self._pf = Prefetcher(ttl=int(cfg["cache_ttl"]), size=int(cfg["cache_size"]))
        self.info = PluginInfo(
            id=self.id,
            name=_("Hindsight memory"),
            description=_("Recalls related memories from the hindsight bank"),
        )

    def _fetch(self, query: str) -> list[dict]:
        cfg = _cfg()
        api_key = os.environ.get("HINDSIGHT_API_KEY", "")
        if not api_key:
            logger.warning("hindsight: HINDSIGHT_API_KEY is not set")
            return []

        body: dict = {
            "query": query,
            "budget": cfg["budget"],
            "max_tokens": int(cfg["max_tokens"]),
        }
        if cfg.get("types"):
            body["types"] = list(cfg["types"])

        url = cfg["url"].rstrip("/") + f"/v1/default/banks/{cfg['bank']}/memories/recall"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        _t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout"])) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.info("hindsight: recall failed: %s", exc)
            return []

        _took = time.monotonic() - _t0
        if _took > 2.0:
            logger.warning("hindsight: slow recall %.2fs for %r", _took, query)

        out: list[dict] = []
        for item in data.get("results") or []:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            scores = item.get("scores") or {}
            semantic = scores.get("semantic")
            if semantic is not None and semantic < float(cfg["min_semantic"]):
                continue
            out.append(
                {
                    "text": text,
                    "when": (item.get("occurred_start") or item.get("mentioned_at") or "")[:10],
                    "final": scores.get("final") or 0.0,
                }
            )
        out.sort(key=lambda i: i["final"], reverse=True)
        return out[: int(cfg["max_results"])]

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

        answers = []
        for item in items:
            label = _("Memory")
            if item["when"]:
                label = f"{label} ({item['when']})"
            answers.append(Answer(answer=f"{label}: {item['text']}"))
        return answers
