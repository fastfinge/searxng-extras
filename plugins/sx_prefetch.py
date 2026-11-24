# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tiny prefetch helper shared by the external search plugins.

A plugin that calls out to another service pays that latency on top of the
engine fan-out.  ``pre_search`` runs *before* the engines, so starting the fetch
there and joining it in ``post_search`` hides the call behind the web engines
instead of adding to them.

The cache is keyed by query text, so a repeated search is instant, and a fetch
that finishes after its request gave up still populates the cache for the next
one.
"""

from __future__ import annotations

import threading
import time
import typing as t


class Prefetcher:
    """Prefetch-cache for one plugin (not shared across plugins)."""

    def __init__(self, ttl: int = 900, size: int = 256) -> None:
        self.ttl = ttl
        self.size = size
        self._cache: dict[str, tuple[float, t.Any]] = {}
        self._inflight: dict[str, tuple[float, threading.Thread, dict]] = {}
        self._lock = threading.Lock()

    # -- cache ---------------------------------------------------------------

    def cached(self, key: str):
        with self._lock:
            hit = self._cache.get(key)
        if hit and (time.monotonic() - hit[0]) < self.ttl:
            return hit[1]
        return None

    def _store(self, key: str, value) -> None:
        with self._lock:
            if len(self._cache) >= self.size:
                for old in sorted(self._cache, key=lambda k: self._cache[k][0])[: max(1, self.size // 8)]:
                    self._cache.pop(old, None)
            self._cache[key] = (time.monotonic(), value)

    # -- prefetch ------------------------------------------------------------

    def prewarm(self, key: str, fetch: t.Callable[[], t.Any]) -> None:
        """Start ``fetch`` in the background unless it is cached or running."""
        if self.cached(key) is not None:
            return
        with self._lock:
            if key in self._inflight:
                return
            now = time.monotonic()
            for stale in [k for k, v in self._inflight.items() if now - v[0] > 120]:
                self._inflight.pop(stale, None)
            holder: dict = {}
            thread = threading.Thread(target=self._run, args=(key, fetch, holder), daemon=True)
            self._inflight[key] = (now, thread, holder)
        thread.start()

    def _run(self, key: str, fetch, holder: dict) -> None:
        try:
            value = fetch()
        except Exception:  # pylint: disable=broad-except
            value = None
        holder["value"] = value
        if value is not None:
            self._store(key, value)

    def get(self, key: str, timeout: float):
        """Return the cached value, or wait up to ``timeout`` for the fetch."""
        value = self.cached(key)
        if value is not None:
            return value
        with self._lock:
            entry = self._inflight.get(key)
        if not entry:
            return None
        _, thread, holder = entry
        thread.join(max(0.0, float(timeout)))
        if thread.is_alive():
            return None
        with self._lock:
            self._inflight.pop(key, None)
        return holder.get("value")
