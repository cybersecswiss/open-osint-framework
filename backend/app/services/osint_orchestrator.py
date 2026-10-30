"""
Fan-out to OSINT modules and collect their RunResponse payloads.

Manifest-driven: every module exposes `GET /manifest` describing its
tools and the query_types each tool accepts. Backend hits each
manifest once at startup (see `refresh_manifests()` called from the
FastAPI lifespan) and caches the result. The orchestrator then
expands a (module_name, query_type) request into the matching tool
calls and runs them concurrently with `asyncio.gather`. A failing
module surfaces as an error entry in the result list rather than
sinking the whole search.

Adding a new module is a one-line change: append `(name, settings_url_attr)`
to `MODULE_REGISTRY` below, ship the module container with `/manifest`,
and rebuild. No frontend or i18n key edits per module are needed
beyond the labels declared in the manifest.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import httpx

from app.config import settings
from app.services.api_keys import load_keys
from app.services.news_feeds import get_feeds

log = logging.getLogger("osint.orchestrator")

# Tool-name collisions already reported — see tool_reliability().
_warned_collisions: set[str] = set()
# Structured record of the same thing, for collisions() above.
_collisions: dict[str, dict] = {}

# (module_name, settings attribute holding the base URL)
# Source of truth — must match docker-compose service names + ports.
MODULE_REGISTRY: list[tuple[str, str]] = [
    ("alias",     "module_alias_url"),
    ("leaks",     "module_leaks_url"),
    ("infra",     "module_infra_url"),
    ("threat",    "module_threat_url"),
    ("darknet",   "module_darknet_url"),
    ("messenger", "module_messenger_url"),
    ("crypto",    "module_crypto_url"),
    ("telegram",  "module_telegram_url"),
    ("compliance", "module_compliance_url"),
    ("forums",     "module_forums_url"),
    ("dating",     "module_dating_url"),
    ("image",      "module_image_url"),
    ("news", "module_news_url"),
    ("corporate", "module_corporate_url"),
]

# Cached manifests, keyed by module name. Populated by
# refresh_manifests(); consumed by run_modules() and the
# /api/v1/search/modules endpoint.
_manifests: dict[str, dict[str, Any]] = {}


def _module_url(name: str) -> str | None:
    for n, attr in MODULE_REGISTRY:
        if n == name:
            return getattr(settings, attr, None)
    return None


async def _fetch_manifest(name: str, base_url: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base_url}/manifest")
            if r.status_code != 200:
                log.warning("manifest %s: HTTP %s", name, r.status_code)
                return None
            data = r.json()
            data["_url"] = base_url
            return data
    except httpx.HTTPError as e:
        log.warning("manifest %s unreachable: %s", name, e)
        return None
    except Exception:  # noqa: BLE001
        log.exception("manifest %s: unexpected error", name)
        return None


async def refresh_manifests() -> dict[str, dict[str, Any]]:
    """Re-poll every registered module's /manifest. Skips unreachable
    modules — the framework keeps working with whatever responded."""
    results = await asyncio.gather(
        *[_fetch_manifest(name, getattr(settings, attr))
          for name, attr in MODULE_REGISTRY],
        return_exceptions=False,
    )
    fresh: dict[str, dict[str, Any]] = {}
    for (name, _), manifest in zip(MODULE_REGISTRY, results):
        if manifest:
            fresh[name] = manifest
    _manifests.clear()
    _manifests.update(fresh)
    log.info("manifests refreshed: %s", sorted(_manifests.keys()))
    # Surface manifest-level defects at BOOT rather than on the first search.
    # tool_reliability() is what detects a shared tool name; calling it here
    # means the operator meets the problem in the startup log instead of
    # discovering it in a finished case file.
    tool_reliability()
    return dict(_manifests)


def get_manifests() -> dict[str, dict[str, Any]]:
    """Read-only snapshot of cached manifests."""
    return {k: dict(v) for k, v in _manifests.items()}


def supported_modules() -> list[str]:
    """Names of modules whose manifest was successfully cached."""
    return sorted(_manifests.keys())


def tool_reliability() -> dict[str, str]:
    """tool name → Admiralty source reliability letter, from the manifests.

    The rating is declared by the module that owns the tool, because only the
    module author knows what KIND of statement its tool makes. The framework
    just collects them here and hands the map to `graph_builder`, which
    combines it with corroboration into the per-finding rating.

    Tools that never declared one are simply absent, and the graph builder
    rates them "F" (cannot be judged).

    ⚠️ **Two modules may declare the same tool NAME.** Example: a
    `telegram_search` once existed in both `messenger` (declaring D) and
    `telegram` (declaring C). This map is keyed by name, so a plain assignment
    let the module that happened to be registered last win — and because
    `telegram` sorts after `messenger`, every finding from the *messenger*
    tool was presented as **C when its own author declared D**.

    One grade too good is the dangerous direction: a tool saying "treat me
    with caution" would be shown as "fairly reliable" in a case file. So a
    collision resolves to the **worse** letter and is logged with both
    modules named. That is a stopgap, not a fix — the real repair is for the
    two tools to stop sharing a name.

    The two were renamed — `messenger/telegram_deeplink_search` and
    `telegram/telegram_deep_search` — and stored provenance can be migrated
    with `scripts/migrate-tool-rename.sh`. The conservative merge below stays as
    the runtime safety net, but a collision is now also reported through
    `collisions()` so the health check and the operator console can show it
    instead of leaving it in a log line nobody greps for.
    """
    out: dict[str, str] = {}
    origin: dict[str, str] = {}
    for module_name, manifest in _manifests.items():
        for tool_desc in manifest.get("tools", []) or []:
            name = tool_desc.get("tool")
            level = tool_desc.get("reliability")
            if not (name and level):
                continue
            letter = str(level).upper()[:1]
            previous = out.get(name)
            if previous is None:
                out[name], origin[name] = letter, module_name
                continue
            if previous != letter:
                # max() on the letters IS the conservative choice: A is the
                # best rating and F the worst, so the later letter wins.
                worse = max(previous, letter)
                # Once per process, not once per search. This map is rebuilt on
                # every single search, and a warning repeated that often is a
                # warning nobody reads.
                _collisions[name] = {
                    "tool": name,
                    "modules": sorted({origin[name], module_name}),
                    "ratings": {origin[name]: previous, module_name: letter},
                    "effective": worse,
                }
                if name not in _warned_collisions:
                    _warned_collisions.add(name)
                    log.warning(
                        "tool name '%s' is declared by both '%s' (%s) and "
                        "'%s' (%s); using the WORSE rating %s. Rename one of "
                        "them — a shared name silently rates one module's "
                        "findings with the other module's letter.",
                        name, origin[name], previous, module_name, letter, worse)
                out[name] = worse
    return out


def collisions() -> list[dict]:
    """Tool names declared by more than one module, with the rating each
    side claimed and the one actually used.

    Exposed rather than merely logged: a collision silently rates one
    module's findings with another module's letter, and "it was in the
    startup log" is not a way to notice that. Empty is the healthy state.
    """
    return sorted(_collisions.values(), key=lambda c: c["tool"])


def known_query_types() -> set[str]:
    """Every query_type accepted by at least one cached tool. Used by
    the search router to reject obviously-unsupported requests with a
    400 up front instead of failing deep in the orchestrator."""
    qts: set[str] = set()
    for manifest in _manifests.values():
        for tool_desc in manifest.get("tools", []) or []:
            qts.update(tool_desc.get("query_types") or [])
    return qts


# Per-tool timeout by the class the module declares in its manifest.
#
# Only "fast" is shortened. "medium" is both the default and the previous
# flat value, so every tool that has NOT been measured keeps exactly the
# behaviour it had — declaring a class can make a tool give up sooner, never
# later, and an undeclared tool is untouched.
#
# 60 s for "fast" is >12x the slowest run ever measured in that group
# (threat_actor_check, 2.1 s median / 4.6 s max across the recorded jobs), so
# it cannot cut off a healthy tool. What it does cut off is a hung source
# holding a slot for five minutes while the investigator waits.
_TIMEOUT_BY_CLASS: dict[str, float] = {"fast": 60.0, "medium": 300.0, "slow": 300.0}
_DEFAULT_TIMEOUT = 300.0

# Plan order: cheap tools first. With a single asyncio.gather this is mostly
# cosmetic today — everything starts at once — but it makes the live progress
# table fill top-down instead of at random, and it is the ordering the
# per-tool incremental flush will need.
_CLASS_ORDER: dict[str, int] = {"fast": 0, "medium": 1, "slow": 2}


def tool_latency() -> dict[str, str]:
    """tool name → declared latency class, from the manifests.

    Same shape and same rule as `tool_reliability()`: declared by the module
    that owns the tool, absent when never declared (the caller then applies
    the "medium" default rather than guessing).
    """
    out: dict[str, str] = {}
    for manifest in _manifests.values():
        for tool_desc in manifest.get("tools", []) or []:
            name = tool_desc.get("tool")
            cls = tool_desc.get("latency_class")
            if name and cls:
                out[name] = str(cls)
    return out


def build_plan(
    modules: list[str], query_type: str, tools: list[str] | None = None
) -> list[tuple[str, str, str, str]]:
    """Expand (modules, query_type) into (module, tool, url, latency_class).

    Split out of run_modules so the expansion and the ordering can be tested
    without touching the network.

    `tools` optionally narrows the plan to named tools. **None or empty means
    all** — the previous behaviour. Unknown names are ignored rather than
    raising: the caller renders its choices from a manifest snapshot that can
    be older than this call.

    A module with no cached manifest becomes a single `<module>` entry with an
    empty url, which run_modules turns into one error row — a module that is
    down must be reported, not silently dropped from the plan.
    """
    wanted = {t for t in (tools or []) if t}
    plan: list[tuple[str, str, str, str]] = []
    for name in modules:
        manifest = _manifests.get(name)
        if not manifest:
            plan.append((name, f"<{name}>", "", "medium"))
            continue
        url = manifest.get("_url") or _module_url(name)
        if not url:
            continue
        for tool_desc in manifest.get("tools", []) or []:
            tool = tool_desc.get("tool")
            qts = tool_desc.get("query_types") or []
            if not tool or query_type not in qts:
                continue
            if wanted and tool not in wanted:
                continue
            plan.append(
                (name, tool, url,
                 str(tool_desc.get("latency_class") or "medium"))
            )

    # Cheap tools first. Stable sort, so within a class the manifest order —
    # i.e. the order the module author chose — is preserved.
    plan.sort(key=lambda p: _CLASS_ORDER.get(p[3], 1))
    return plan


async def _call_module(
    module_url: str, tool: str, query: str, query_type: str, job_id: str,
    credentials: dict[str, str] | None = None,
    feeds: list[dict[str, Any]] | None = None,
    channels: list[str] | None = None,
    forums: list[str] | None = None,
    onion_forums: list[dict[str, Any]] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    client: "httpx.AsyncClient | None" = None,
) -> dict[str, Any]:
    # `options.credentials` carries the operator-global API keys (managed
    # in the Global-Admin Settings tab) so a saved key takes effect with
    # no container restart. Modules read these first, then fall back to
    # their own .env values.
    # `options.feeds` does the same for the operator's RSS/news feed list;
    # module-news falls back to its bundled defaults when it is empty.
    options: dict[str, Any] = {"credentials": credentials or {}}
    if feeds:
        options["feeds"] = feeds
    # Operator-maintained Telegram channel list for the username sweep. Same
    # contract as `feeds`: sent only when non-empty, so an empty store leaves
    # the module on its bundled file instead of sweeping nothing.
    if channels:
        options["channels"] = channels
    # Operator-maintained crime-forum list for the forum hunt. Same contract
    # again: sent only when non-empty, so an empty store leaves the module on
    # its built-in list instead of dorking nothing.
    if forums:
        options["forums"] = forums
    # Known onion forums — a recognition table for the darknet sweep, so a
    # hit stops being an anonymous hidden service.
    if onion_forums:
        options["onion_forums"] = onion_forums
    payload = {"job_id": job_id, "tool": tool, "query": query,
               "query_type": query_type, "options": options}
    try:
        if client is not None:
            # One pooled client per search instead of a fresh connection pool
            # per tool — a broad search makes 40-70 of these calls.
            r = await client.post(f"{module_url}/run", json=payload, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as own:
                r = await own.post(f"{module_url}/run", json=payload)
        r.raise_for_status()
        return r.json()
    except httpx.TimeoutException:
        # NOT "unreachable". A long crime_forum_hunt run over dozens of onion
        # forums can hit this at exactly the 300 s limit; it used to be
        # reported to the investigator as "module unreachable:" — with an empty message,
        # because `str(httpx.ReadTimeout)` is the empty string. That sends
        # somebody to check a container that is healthy and answering, and it
        # hides the one fact that matters: the tool was cut off, so its part
        # of the search is INCOMPLETE rather than empty.
        log.warning("module call %s/%s timed out after %.0fs", module_url, tool, timeout)
        return {
            "job_id": job_id, "tool": tool, "status": "error",
            "duration_seconds": timeout, "findings": [], "edges": [],
            "errors": [f"tool timed out after {timeout:.0f}s — the module is "
                       f"running and answering, it just did not finish in "
                       f"time. Its results are missing from this search, not "
                       f"empty. Narrow the query or stop and re-run with "
                       f"fewer tools."],
        }
    except httpx.HTTPError as e:
        # `or type(e).__name__`: several httpx transport errors carry an empty
        # message, and a bare "module unreachable:" tells nobody anything.
        log.warning("module call %s/%s failed: %s", module_url, tool, e)
        return {
            "job_id": job_id, "tool": tool, "status": "error",
            "duration_seconds": 0, "findings": [], "edges": [],
            "errors": [f"module unreachable: {e or type(e).__name__}"],
        }
    except Exception as e:  # noqa: BLE001
        log.exception("unexpected orchestrator error for %s", tool)
        return {
            "job_id": job_id, "tool": tool, "status": "error",
            "duration_seconds": 0, "findings": [], "edges": [],
            "errors": [str(e)],
        }


async def run_modules(
    query: str,
    query_type: str,
    modules: list[str],
    job_id: str,
    on_progress: "Callable[..., Awaitable[None]] | None" = None,
    on_module_complete: "Callable[..., Awaitable[None]] | None" = None,
    on_tool_complete: "Callable[..., Awaitable[None]] | None" = None,
    tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run every tool from every requested module whose query_types
    accept the request's query_type. Tools with no matching
    query_type are silently skipped.

    `on_progress` (optional async callable) is invoked twice per tool:
    once with status='running' before the call, and once with
    status='done'|'partial'|'error' + finding/edge counts + duration
    after the call returns. The search router uses this to populate
    the SearchJob.tool_progress JSON column so the frontend's
    polling loop can render a per-tool live status table.

    `on_tool_complete(module, tool, result)` (optional async callable) fires
    as soon as a SINGLE tool returns. This is what the search router uses to
    persist incrementally: per module, every finding waited for that module's
    slowest tool (in `alias`, four tools finish long before handle_sweep's
    ~600 probes), so the case graph stayed empty while results already
    existed.

    `on_module_complete(module, results)` (optional) fires ONCE per module as
    soon as ALL of that module's tools have returned, carrying just that
    module's result dicts. Kept for callers that want module granularity; the
    search router no longer passes it, because passing BOTH would append every
    result twice.

    Exceptions from either hook are logged and swallowed — a persist hiccup
    must not sink a search that already has findings. The caller's FINAL
    flush is where a failure is allowed to mark the job failed."""
    if not _manifests:
        await refresh_manifests()

    plan = build_plan(modules, query_type, tools)

    if not plan:
        return [{
            "job_id": job_id, "tool": "<orchestrator>", "status": "error",
            "duration_seconds": 0, "findings": [], "edges": [],
            "errors": [f"No tools matched modules={modules} for query_type={query_type}"
                       + (f" and tools={sorted(set(tools))}" if tools else "")
                       + f". Registered modules: {supported_modules()}"],
        }]

    # Notify the caller that every planned tool is queued (pending)
    # so the UI can render the full row list immediately, even before
    # any tool returns.
    if on_progress:
        for module, tool, _url, _cls in plan:
            await on_progress(module=module, tool=tool, status="pending",
                              findings=0, edges=0, errors=[], duration=0.0)

    # Load the operator-global API keys once per search (cached in the
    # api_keys service), then pass them to every module call.
    try:
        credentials = await load_keys()
    except Exception:  # noqa: BLE001 — never fail a search over key loading
        credentials = {}

    # Operator-maintained news feeds, same idea. Empty list is fine: the
    # module then uses its own verified defaults.
    try:
        feeds = await get_feeds()
        if feeds:
            from app.services import news_feeds as _nf
            feeds = _nf.apply_placeholders(feeds, await _nf.get_settings())
    except Exception:  # noqa: BLE001
        feeds = []

    # Operator-maintained Telegram channel list (Owner console). Empty means
    # "module, use your own file" — never "sweep nothing".
    try:
        from app.services.telegram_channels import get_active_handles
        channels = await get_active_handles()
    except Exception:  # noqa: BLE001
        channels = []

    # Operator-maintained crime-forum list (Owner console). Empty means
    # "module, use your own list" — never "dork nothing".
    try:
        from app.services.crime_forums import get_active_domains, get_active_onions
        forums = await get_active_domains()
        # Known onion forums travel separately: they are a recognition table
        # for the Tor sweep, not dork targets. Mixing them into `forums`
        # would spend a clearnet query per hidden service to find nothing.
        onion_forums = await get_active_onions()
    except Exception:  # noqa: BLE001
        forums = []
        onion_forums = []

    # Per-module completion tracking: fire on_module_complete once a
    # module's last tool returns, carrying that module's results.
    from collections import defaultdict
    remaining: dict[str, int] = defaultdict(int)
    module_results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for module, _tool, _url, _cls in plan:
        remaining[module] += 1
    mod_lock = asyncio.Lock()

    async def _wrapped(module: str, tool: str, url: str, cls: str,
                       client: httpx.AsyncClient) -> dict[str, Any]:
        if not url:
            res = {
                "job_id": job_id, "tool": tool, "status": "error",
                "duration_seconds": 0, "findings": [], "edges": [],
                "errors": [f"module {module} not registered or manifest unreachable"],
            }
        else:
            if on_progress:
                await on_progress(module=module, tool=tool, status="running",
                                  findings=0, edges=0, errors=[], duration=0.0)
            res = await _call_module(
                url, tool, query, query_type, job_id, credentials, feeds,
                channels=channels, forums=forums, onion_forums=onion_forums,
                timeout=_TIMEOUT_BY_CLASS.get(cls, _DEFAULT_TIMEOUT),
                client=client,
            )
        if on_progress:
            await on_progress(
                module=module, tool=tool, status=res.get("status", "?"),
                findings=len(res.get("findings") or []),
                edges=len(res.get("edges") or []),
                errors=res.get("errors") or [],
                notes=res.get("notes") or [],
                duration=res.get("duration_seconds") or 0.0,
            )
        if on_tool_complete:
            try:
                await on_tool_complete(module, tool, res)
            except Exception:  # noqa: BLE001 — a persist hiccup must not kill the search
                log.exception("on_tool_complete(%s/%s) failed", module, tool)
        if on_module_complete:
            async with mod_lock:
                module_results[module].append(res)
                remaining[module] -= 1
                fire = list(module_results[module]) if remaining[module] == 0 else None
            if fire is not None:
                try:
                    await on_module_complete(module, fire)
                except Exception:  # noqa: BLE001 — a persist hiccup must not kill the search
                    log.exception("on_module_complete(%s) failed", module)
        return res

    # One client for the whole fan-out. The per-request timeout still comes
    # from the tool's class; the client-level one is only the ceiling.
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        return list(await asyncio.gather(
            *[_wrapped(m, t, u, c, client) for m, t, u, c in plan]
        ))
