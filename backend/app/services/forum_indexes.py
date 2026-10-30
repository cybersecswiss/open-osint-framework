"""Status and scheduled refresh of the two forum reference indexes.

module-forums carries two content-independent lookup indexes:

* **threat_actors** — ~830 k usernames from 25 crime forums
  (spmedia/Threat-Actor-Usernames-Scrape). Answers "is this handle a known
  crime-forum actor, and where".
* **linkbase** — the link-base.ms directory of forums and markets.

Both already had a refresh endpoint on the module and neither was ever
called: the `/cache` volume stayed empty and both indexes remained the
copies baked into the image, going stale by the day. A refresh button nobody presses is a stale index with extra steps, which is
why this exists.

**What is NOT here, and why.** This is deliberately not a store of forum
*content* or of case findings. Those two would be a different thing
entirely: findings belong to the customer's agent (architecture rule 1; a
cross-search result cache was explicitly rejected for that reason), and crawling forum
content would mean the operator holding criminal material fetched from their
own address. What refreshes here is reference data about WHICH handles and
boards exist — no case link, no content.

**One refresh per tick, on purpose.** Rebuilding the actor index holds the
loaded index and the new dict at the same time (~345 MB + ~350 MB). That
allocation alone can get the container OOM-killed; with a 1 GB limit,
running both rebuilds concurrently would put it straight back at the edge.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

from app.config import settings

log = logging.getLogger("osint.forum_indexes")

# Refresh interval. Weekly by default: these are slow-moving reference lists
# (a forum handle set does not change hourly) and the linkbase crawl alone
# takes ~10 minutes at a rate-limit-respecting pace.
REFRESH_DAYS = int(os.environ.get("FORUM_INDEX_REFRESH_DAYS", "7") or 7)

# id → (status endpoint, refresh endpoint, label)
INDEXES: dict[str, tuple[str, str]] = {
    "threat_actors": ("/threat-actors/status", "/threat-actors/refresh"),
    "linkbase": ("/linkbase/status", "/linkbase/refresh"),
}

# The memory-heavy one goes first when both are due, because it is the one
# whose staleness actually costs findings.
ORDER = ["threat_actors", "linkbase"]


def _base() -> str:
    return settings.module_forums_url.rstrip("/")


def _age_days(mtime: str | None) -> float | None:
    if not mtime:
        return None
    try:
        # The module reports naive UTC (`datetime.utcnow().isoformat()`).
        dt = datetime.fromisoformat(str(mtime).replace("Z", ""))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return round((datetime.utcnow() - dt).total_seconds() / 86400.0, 2)


async def get_status() -> dict:
    """Both indexes: age, entry count, refresh state, and whether due.

    Degrades rather than raising: a module that is down is reported as
    `reachable: false` with the rest of the console still usable. An
    unreachable module is an operator-side fact, not a statement that the
    index is stale — so `due` is False in that case, and nothing gets
    triggered on the back of it.
    """
    out: dict[str, dict] = {}
    reachable = True
    async with httpx.AsyncClient(timeout=15) as client:
        for name in ORDER:
            status_path, _ = INDEXES[name]
            try:
                r = await client.get(f"{_base()}{status_path}")
                r.raise_for_status()
                data = r.json() or {}
            except Exception as e:  # noqa: BLE001
                reachable = False
                out[name] = {"error": f"{type(e).__name__}", "due": False}
                continue
            refresh = data.get("refresh") or {}
            age = _age_days(data.get("index_mtime"))
            running = refresh.get("state") == "running"
            out[name] = {
                "index_mtime": data.get("index_mtime"),
                "age_days": age,
                "active_index": data.get("active_index"),
                # True while the baked seed is in use — i.e. the volume copy
                # has never been written. Worth showing: it is the state the
                # whole system sat in for 20 days without anyone noticing.
                "using_baked_seed": "/cache/" not in str(data.get("active_index") or ""),
                "state": refresh.get("state") or "idle",
                "last_error": refresh.get("error"),
                # From the index FILE first (survives a module restart), and
                # only then from the in-process refresh state. The other way
                # round, every deploy blanked the counts for an index that
                # was perfectly fine.
                "entries": (data.get("entries")
                            if data.get("entries") is not None
                            else (refresh.get("username_count")
                                  or refresh.get("board_count"))),
                # How many forums this index COVERS. Reported so the number
                # cannot be mistaken for the operator's dork list, which
                # lives in the same console tab and is a different thing
                # entirely.
                "forums": data.get("forums"),
                "dead_forums": data.get("dead_forums"),
                "running": running,
                "due": bool(not running and (age is None or age >= REFRESH_DAYS)),
            }
    return {"indexes": out, "reachable": reachable, "refresh_days": REFRESH_DAYS}


async def trigger(name: str) -> dict:
    """Kick off one refresh. Returns immediately — the module runs it in a
    background thread and reports progress through its status endpoint."""
    if name not in INDEXES:
        raise ValueError(f"unknown index '{name}'")
    _, refresh_path = INDEXES[name]
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{_base()}{refresh_path}")
        r.raise_for_status()
        return r.json() or {}


async def refresh_due() -> dict:
    """Trigger **at most one** due index. Called by the scheduler.

    One per tick is the memory guard described in the module docstring, and
    it also keeps the linkbase crawl (~10 min, rate-limit-respecting) from
    running on top of an actor-index rebuild.
    """
    status = await get_status()
    if not status["reachable"]:
        return {"triggered": None, "reason": "module-forums unreachable"}
    for name in ORDER:
        info = status["indexes"].get(name) or {}
        if info.get("running"):
            # Something is already rebuilding — never start a second one.
            return {"triggered": None, "reason": f"{name} already running"}
        if info.get("due"):
            res = await trigger(name)
            log.info("scheduler: forum index '%s' refresh triggered (age %s d): %s",
                     name, info.get("age_days"), res.get("state"))
            return {"triggered": name, "age_days": info.get("age_days"),
                    "result": res}
    return {"triggered": None, "reason": "nothing due"}
