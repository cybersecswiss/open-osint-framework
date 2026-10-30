import os
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.crime_forum_runner import run_crime_forum_hunt
from tools.forum_check import check_forums
from tools.linkbase_runner import run_linkbase_lookup
from tools.threat_actor_runner import run_threat_actor_check
from tools.pgp_runner import run_pgp_lookup
from tools import linkbase_crawl, threat_actor_crawl, threat_actor_runner

app = FastAPI(title="OSINT Module: Crime Forums", docs_url=None, redoc_url=None)

CACHE_INDEX = Path(os.getenv("LINKBASE_CACHE", "/cache/linkbase_index.json"))
TA_CACHE = Path(os.getenv("THREAT_ACTORS_CACHE", "/cache/threat_actors.json.gz"))


MANIFEST = ManifestResponse(
    name="forums",
    label_key="search.module_forums",
    category="forums",
    description_key="search.module_forums_desc",
    tools=[
        ToolDescriptor(
            tool="crime_forum_hunt",
            latency_class="slow",
            reliability="D",
            label_key="search.tool_crime_forum_hunt",
            # username + literal contact IDs actors advertise on forums
            # (Jabber/XMPP, Tox, Session) + free keyword.
            query_types=["username", "jabber_id", "tox_id", "session_id", "keyword"],
            default_query_type="username",
        ),
        ToolDescriptor(
            tool="linkbase_lookup",
            latency_class="fast",
            reliability="C",
            label_key="search.tool_linkbase_lookup",
            query_types=["keyword"],
            default_query_type="keyword",
        ),
        ToolDescriptor(
            tool="threat_actor_check",
            latency_class="fast",
            reliability="C",
            label_key="search.tool_threat_actor_check",
            query_types=["username"],
            default_query_type="username",
        ),
        ToolDescriptor(
            tool="pgp_lookup",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_pgp_lookup",
            # email → key → other emails on that key (deanon), and
            # fingerprint → all UIDs. Keyless (public keyservers).
            query_types=["pgp_fingerprint", "email"],
            default_query_type="pgp_fingerprint",
        ),
    ],
)


# --- LinkBase index refresh (slow crawl, background) -----------------
_refresh: dict = {"state": "idle", "started": None, "finished": None,
                  "board_count": None, "error": None}
_refresh_lock = threading.Lock()


def _do_refresh():
    try:
        index = linkbase_crawl.crawl(interval=2.0)
        CACHE_INDEX.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_INDEX.with_suffix(".tmp")
        tmp.write_text(__import__("json").dumps(index, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(CACHE_INDEX)
        _refresh.update(state="done", finished=datetime.utcnow().isoformat(),
                        board_count=index["board_count"], error=None)
    except Exception as e:  # noqa: BLE001
        _refresh.update(state="error", finished=datetime.utcnow().isoformat(),
                        error=f"{type(e).__name__}: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.get("/linkbase/status")
async def linkbase_status():
    baked = Path(__file__).resolve().parent / "data" / "linkbase_index.json"
    active = CACHE_INDEX if CACHE_INDEX.is_file() else (baked if baked.is_file() else None)
    info = {"refresh": _refresh, "active_index": str(active) if active else None}
    if active:
        info["index_mtime"] = datetime.utcfromtimestamp(active.stat().st_mtime).isoformat()
    # Same reason as the threat-actor status: the count must survive a
    # restart, so it is read from the file rather than from refresh state.
    # Cheap here — 289 records, no gzip.
    try:
        import json as _json
        with open(active, encoding="utf-8") as fh:
            info["entries"] = (_json.load(fh) or {}).get("board_count")
    except Exception as e:  # noqa: BLE001
        info["count_error"] = f"{type(e).__name__}"
    return info


@app.post("/linkbase/refresh")
async def linkbase_refresh():
    """Trigger a slow (~10 min, rate-limit-respecting) re-crawl of link-base.ms
    into the /cache volume. Returns immediately; poll /linkbase/status."""
    with _refresh_lock:
        if _refresh["state"] == "running":
            return {"state": "running", "note": "a refresh is already in progress"}
        _refresh.update(state="running", started=datetime.utcnow().isoformat(),
                        finished=None, board_count=None, error=None)
    threading.Thread(target=_do_refresh, daemon=True).start()
    return {"state": "running", "note": "crawling link-base.ms (~10 min); poll /linkbase/status"}


# --- Threat-actor username index refresh -----------------------------
_ta_refresh: dict = {"state": "idle", "finished": None,
                     "username_count": None, "error": None}
_ta_lock = threading.Lock()


def _do_ta_refresh():
    try:
        TA_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(TA_CACHE) + ".tmp"
        # crawl writes the gzip itself given an output path
        import sys as _sys
        argv_bak = _sys.argv
        _sys.argv = ["threat_actor_crawl.py", tmp]
        try:
            threat_actor_crawl.main()
        finally:
            _sys.argv = argv_bak
        os.replace(tmp, TA_CACHE)
        import gzip as _gz, json as _json
        with _gz.open(TA_CACHE, "rt", encoding="utf-8") as f:
            cnt = _json.load(f).get("username_count")
        _ta_refresh.update(state="done", finished=datetime.utcnow().isoformat(),
                           username_count=cnt, error=None)
    except Exception as e:  # noqa: BLE001
        _ta_refresh.update(state="error", finished=datetime.utcnow().isoformat(),
                           error=f"{type(e).__name__}: {e}")


@app.get("/threat-actors/status")
async def threat_actors_status():
    baked = Path(__file__).resolve().parent / "data" / "threat_actors.json.gz"
    active = TA_CACHE if TA_CACHE.is_file() else (baked if baked.is_file() else None)
    info = {"refresh": _ta_refresh, "active_index": str(active) if active else None}
    if active:
        info["index_mtime"] = datetime.utcfromtimestamp(active.stat().st_mtime).isoformat()
    # Counts from the INDEX FILE, not from `_ta_refresh`.
    #
    # That dict is per-process state and resets on every container restart,
    # so after any deploy the console showed no numbers at all for a
    # perfectly good index — "862 637 handles" silently became blank, which
    # reads as "the index is gone".
    #
    # `_load()` is the same memoised loader the search path uses (keyed by
    # path+mtime), so this shares its object rather than parsing a second
    # copy into memory. Run in a thread: it is a synchronous multi-second
    # parse the first time after a restart.
    try:
        data = await run_in_threadpool(threat_actor_runner._load)
        if isinstance(data, dict) and data.get("index"):
            info["entries"] = data.get("username_count")
            # How many forums the INDEX covers. Deliberately reported next to
            # the handle count: without it the number floats free, and in a
            # console that also shows a 12-entry forum list it invites the
            # reading that the two are the same thing. They are not.
            info["forums"] = data.get("forum_count")
            info["dead_forums"] = len(data.get("dead_forums") or [])
    except Exception as e:  # noqa: BLE001 — status must never 500
        info["count_error"] = f"{type(e).__name__}"
    return info


@app.post("/threat-actors/refresh")
async def threat_actors_refresh():
    """Re-download spmedia/Threat-Actor-Usernames-Scrape into the /cache
    volume. Returns immediately; poll /threat-actors/status."""
    with _ta_lock:
        if _ta_refresh["state"] == "running":
            return {"state": "running", "note": "a refresh is already in progress"}
        _ta_refresh.update(state="running", finished=None,
                           username_count=None, error=None)
    threading.Thread(target=_do_ta_refresh, daemon=True).start()
    return {"state": "running", "note": "downloading threat-actor lists; poll /threat-actors/status"}


# --- Forum health check (Owner console) ------------------------------

class ForumCheckRequest(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=200)
    # "index" — search-engine coverage, no contact with the forum (default)
    # "reach" — Tor reachability
    # "both"
    mode: str = "index"
    options: dict = Field(default_factory=dict)


@app.post("/forum-check")
async def forum_check(req: ForumCheckRequest):
    """Probe the operator's forum list. Called by the framework's Owner
    console, not part of the tool manifest — this answers a question about
    the CONFIGURATION, not about a case, so it must never turn up as a
    searchable tool or write anything into a case graph.

    Lives here rather than in the backend because both probes need what this
    container has: the Tor SOCKS proxy for the reachability check, so the
    framework never connects to a crime forum from the operator's own
    address.
    """
    if req.mode not in ("index", "reach", "access", "both"):
        return {"error": f"unknown mode '{req.mode}'", "results": {}}
    results = await check_forums(req.domains, req.mode, req.options)
    return {"mode": req.mode, "checked": len(results), "results": results}


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "crime_forum_hunt":
            findings, edges, errors = await run_crime_forum_hunt(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "linkbase_lookup":
            findings, edges, errors = await run_linkbase_lookup(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "pgp_lookup":
            findings, edges, errors = await run_pgp_lookup(req.query, req.query_type, req.options)
        elif req.tool == "threat_actor_check":
            findings, edges, errors = await run_threat_actor_check(
                req.query, req.query_type, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
