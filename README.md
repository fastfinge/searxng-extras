# searxng-extras

Plugins and API engines for a self-hosted [SearXNG](https://docs.searxng.org/) —
the bits that make a metasearch engine also search *your* stuff: your notes and
memories, your fediverse instance, your own browsing history.

Everything here talks HTTP with the standard library. No extra packages, no
custom SearXNG image.

## What's inside

**plugins/** — loaded by SearXNG from `./plugins` (see install below)

| file | id | what it does |
| --- | --- | --- |
| `hindsight.py` | `hindsight` | Semantic recall against a [Hindsight](https://nousresearch.com) memory bank, rendered in the Answers box above the results |
| `iceshrimp.py` | `iceshrimp` | `/api/v2/search` on an Iceshrimp (or Mastodon-compatible) instance, as result cards |
| `lemmy.py` | `lemmy` | `/api/v3/search` on a Lemmy instance, as result cards |
| `sx_prefetch.py` | — | Shared helper: start the remote call in `pre_search`, collect it in `post_search` |

**engines/** — API-backed search engines, copied into SearXNG's `searx/engines/`

| file | engine | notes |
| --- | --- | --- |
| `serper_api.py` | `serper_api` | Google results via Serper |
| `tavily_api.py` | `tavily_api` | Tavily |
| `linkup_api.py` | `linkup_api` | Linkup |
| `querit_api.py` | `querit_api` | Querit |
| `you_api.py` | `you_api` | You.com |
| `nogon_api.py` | `nogon_api` | A self-hosted browsing-history index ([Nogon](https://github.com/asciimoo/nogon)) |

## Why the prefetch helper

A plugin that calls a remote service in `post_search` serialises its latency on
top of the engine fan-out: search takes engines + your API call. SearXNG runs
`pre_search` *before* it fans out to the engines and `post_search` *after*, so
starting the call in `pre_search` and joining it in `post_search` hides most of
the remote latency behind the engines:

```python
from sx_prefetch import Prefetcher

self._pf = Prefetcher(ttl=900, size=256)            # __init__
self._pf.prewarm(key, lambda: self._fetch(query))   # pre_search
items = self._pf.get(key, join_timeout) or []       # post_search
```

`get()` returns `None` when the fetch is still running at the deadline, so always
fail open. Size `join_timeout` **above** the service's real latency: a 3.5 s
recall behind a 1.5 s fan-out needs ~5 s of join budget or answers silently
disappear on cold searches. Repeat queries are served from the TTL cache and cost
nothing.

## Install

### Plugins

SearXNG loads third-party plugins from the directory on `PYTHONPATH`; the docker
image uses `/usr/local/searxng/custom_plugins`, usually bind-mounted from
`./plugins`:

```yaml
services:
  core:
    volumes:
      - ./plugins:/usr/local/searxng/custom_plugins:ro
    environment:
      # only the plugins you enable need their secrets passed through here
      - HINDSIGHT_API_KEY=${HINDSIGHT_API_KEY}
      - ICESHRIMP_TOKEN=${ICESHRIMP_TOKEN}
```

Copy `plugins/*.py` into that directory. A plugin change needs a container
restart — there is no reload.

Then register them in `settings.yml`. **The `plugins:` block replaces the
upstream defaults instead of merging**, so repeat every built-in you want to
keep — see `settings-example.yml`. Per-plugin settings go in a top-level block
named after the plugin id, never under `plugins:`.

```yaml
plugins:
  searx.plugins.calculator.SXNGPlugin: {active: true}
  # … the rest of the built-ins
  hindsight.HindsightMemory: {active: true}
  iceshrimp.IceshrimpSearch: {active: true}
  lemmy.LemmySearch: {active: true}

hindsight:
  url: http://127.0.0.1:9177
  bank: hermes
```

Secrets for plugins come from the environment; SearXNG's `.env` is substituted
into `docker-compose.yml` but is **not** injected into the container on its own.

### Engines

Copy `engines/*.py` into `searx/engines/` (in the image that is
`/usr/local/searxng/searx/engines/`, bind-mounted the same way as the config) and
add an entry under `engines:`:

```yaml
engines:
  - name: serper
    engine: serper_api
    shortcut: sp
    categories: [general]
    api_key: "YOUR_KEY"
    results_per_page: 20
```

Module-level names in an engine file (`api_key`, `search_url`,
`results_per_page`, …) are overridable per-engine from `settings.yml`, which is
where every credential belongs.

`nogon_api.py` talks to a Nogon instance:

```yaml
  - name: history
    engine: nogon_api
    shortcut: hist
    search_url: http://127.0.0.1:4433/search
    access_token: "YOUR_TOKEN"
```

## Configuration reference

`hindsight:`

| key | default | meaning |
| --- | --- | --- |
| `url` | `http://127.0.0.1:9177` | Hindsight API base |
| `bank` | `hermes` | memory bank to recall from |
| `budget`, `max_tokens` | `low`, `800` | recall budget: `low` keeps latency sane; the default 4096 balloons to ~7 s |
| `max_results` | `5` | answers rendered |
| `types` | `[]` | `[]` = every fact type; `[observation]` is ~1.5 s faster but only returns consolidated notes; `[world, experience]` is fastest but returns raw facts |
| `join_timeout` | `5.0` | seconds to wait in `post_search`; must exceed real recall latency |
| `min_semantic` | `0.62` | similarity floor — below this you get vaguely-worded noise |
| `timeout`, `cache_ttl`, `cache_size` | `8.0`, `900`, `256` | HTTP timeout, result cache |

Key: `HINDSIGHT_API_KEY` (environment).

`iceshrimp:` — `base_url`, `limit` (5), `timeout`, `join_timeout`, `cache_ttl`,
`cache_size`. Key: `ICESHRIMP_TOKEN` (environment; mint one with `read` scope).

`lemmy:` — `base_url`, `limit` (5), `sort` (`TopAll`), `timeout`, `join_timeout`,
`cache_ttl`, `cache_size`. No auth on public instances.

All three plugins skip bangs, queries under three characters, and math-shaped
queries (`2+2`, `sqrt(16)`) so they don't crowd the Answers box with memories for
a calculator query. Iceshrimp and Lemmy search is AND-ish, so both retry once
with the two longest words if a multi-word query comes back empty.

## Caveats

- Tested against SearXNG (2026 releases) with `format=json` and the default
  templates. Plugin API is not stable upstream; pin your image.
- Hindsight recall is the slow part: 2.7–4.4 s per uncached search. That is the
  remote embedding + rerank, not this code.
- Result cards come from third-party instances; the HTML in them is escaped with
  `html.escape(..., quote=False)` before it reaches the template, which renders
  content with `|safe`.
- No credentials live in this repository. If you add one, you did it wrong.

## License

AGPL-3.0-or-later — the plugins import SearXNG internals, so they inherit its
license.
