"""Operator-managed crime-forum list for the forum hunt.

Stored in the license-server's `platform-settings` under a single JSON key,
exactly like the Telegram channels, the RSS feeds and the API keys —
operator-global, editable from the Owner console, effective immediately
without a container restart. The list is handed to module-forums per search
(`options.forums`), so the module never talks to the license-server itself.

Previously the list lived in `_DEFAULT_FORUMS` inside
`modules/forums/tools/crime_forum_runner.py`, overridable only through the
`CRIME_FORUMS` env var — i.e. adding a forum meant editing a container's
environment and restarting it. Crime forums are seized, renamed and reborn
under new domains several times a year; that cadence does not fit a redeploy.

**Why `enabled` is a separate flag, same as the Telegram pool.** Every hunt
dorks one search-engine query PER ENABLED FORUM. The pool is a reference
list; the enabled subset is what each search actually costs in API calls and
wall-clock. The module caps the enabled set at `CRIME_FORUM_MAX` for exactly
that reason and reports what it left out.

Domains are NOT secret: they are public host names, stored in clear.

**The health check runs in module-forums, not here** (see `check_forums`).
Both probes need what that container has and this one does not: the Tor
SOCKS proxy, so the reachability probe never connects to a crime forum from
the operator's own address.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid

import httpx

from app.config import settings

log = logging.getLogger("osint.crime_forums")

STORE_KEY = "CRIME_FORUMS_JSON"

_TTL = 30.0
_cache: dict[str, tuple[float, list[dict]]] = {}

# The list that has been baked into the runner. Kept here so the console can
# seed an empty store with something sensible on day one — the same role the
# bundled `crime_channels.txt` plays for the Telegram sweep.
#
# Categories describe what an analyst would expect to FIND there, because
# that is what decides whether a forum is worth a query for a given case.
DEFAULT_FORUMS: list[tuple[str, str]] = [
    ("xss.is", "russian"),
    ("exploit.in", "russian"),
    ("breachforums.st", "leaks"),
    ("leakbase.io", "leaks"),
    ("leakzone.net", "leaks"),
    ("nulled.to", "cracking"),
    ("cracked.io", "cracking"),
    ("cracked.sh", "cracking"),
    ("hackforums.net", "hacking"),
    ("sinister.ly", "hacking"),
    ("ogusers.gg", "accounts"),
    ("blackhatworld.com", "blackhat"),
]

CATEGORIES = ["russian", "leaks", "cracking", "hacking", "accounts",
              "blackhat", "carding", "darknet", "other"]

# A host name, loosely: labels separated by dots, a TLD of at least two
# letters. Deliberately permissive about the TLD — these forums live on
# .is, .su, .sh, .gg, .cx and whatever else is registrable this year.
_DOMAIN_RE = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")

# Tor hidden services: v3 is 56 base32 chars, v2 (long dead but still listed
# in older directories) is 16.
_ONION_RE = re.compile(r"^([a-z2-7]{56}|[a-z2-7]{16})\.onion$")

SURFACE_CLEARNET = "clearnet"
SURFACE_ONION = "onion"


def surface_of(host: str) -> str:
    return SURFACE_ONION if str(host or "").endswith(".onion") else SURFACE_CLEARNET


def normalize_domain(value: str) -> str:
    """`https://XSS.is/forum/`, `www.xss.is`, `xss.is` → `xss.is`.

    Lower-cased and stripped of scheme, `www.`, path, port and any `@`
    userinfo. Host names are case-insensitive, and storing two casings of one
    forum would dork it twice and show the operator a count that is wrong.

    **Onion addresses are accepted.** They were rejected
    at first because the clearnet dork cannot use them — but "cannot be
    dorked" is not "does not belong here": these are the same forums, and
    the tool's Tor half can both probe them and recognise them when the
    darknet sweep turns one up. What differs is the SURFACE, and that is now
    a field rather than a reason to drop the row.

    Returns "" for anything that is not a plausible host name, so a pasted
    sentence cannot become a "forum" that every search then queries in vain.
    """
    v = str(value or "").strip().lower()
    if not v:
        return ""
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)   # scheme
    v = v.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    v = v.rsplit("@", 1)[-1]                       # userinfo
    v = v.split(":", 1)[0]                         # port
    v = re.sub(r"^www\.", "", v)
    v = v.strip(".")
    if v.endswith(".onion"):
        # Validated strictly: an onion address is a public key, so a typo is
        # not a reachable-but-wrong host, it is nothing at all. Storing a
        # malformed one would mean probing it forever for no answer.
        return v if _ONION_RE.match(v) else ""
    return v if _DOMAIN_RE.match(v) else ""


def normalize(item: dict) -> dict:
    domain = normalize_domain(item.get("domain") or item.get("url") or "")
    return {
        "id": str(item.get("id") or uuid.uuid4()),
        "domain": domain,
        # Derived, never taken from the caller: the host itself decides which
        # half of the tool can use it, and letting an import claim otherwise
        # would put an onion into the clearnet dork loop.
        "surface": surface_of(domain),
        # Free-text label from the source list (e.g. "BreachForums"). Used to
        # name a darknet hit instead of leaving it an anonymous onion.
        "name": (str(item.get("name") or "").strip())[:80],
        "category": (str(item.get("category") or "other").strip().lower())[:32],
        "note": (str(item.get("note") or "").strip())[:200],
        "source": (str(item.get("source") or "manual").strip())[:40],
        "enabled": bool(item.get("enabled", False)),
        # Health-check results, filled by apply_check(). "" = never checked,
        # which is deliberately different from "checked and fine": without
        # that distinction an empty column reads as a verdict.
        "index_status": (str(item.get("index_status") or "").strip())[:20],
        "index_count": int(item.get("index_count") or 0),
        "reach_status": (str(item.get("reach_status") or "").strip())[:20],
        "reach_note": (str(item.get("reach_note") or "").strip())[:60],
        # Guest readability (`access` probe). Answers the
        # question that decides what can be built per forum at all: can this
        # board be read without an account, and does its software address a
        # profile by NAME (so a per-handle check is even possible) or by a
        # numeric id (so it never will be).
        "access_status": (str(item.get("access_status") or "").strip())[:20],
        "access_note": (str(item.get("access_note") or "").strip())[:60],
        "software": (str(item.get("software") or "").strip())[:20],
        "profile_template": (str(item.get("profile_template") or "").strip())[:120],
        "title": (str(item.get("title") or "").strip())[:120],
        "checked_at": (str(item.get("checked_at") or "").strip())[:32],
        # Probe HISTORY for the two probes that touch the host. See
        # PROBE_LOG_LEN below for why a single result is not enough.
        "reach_log": _clean_log(item.get("reach_log")),
        "access_log": _clean_log(item.get("access_log")),
    }


# How many outcomes per probe are remembered. Ten is enough to distinguish
# "answers sometimes" from "never answers" and small enough that 334 forums
# stay a JSON blob the license server happily stores.
PROBE_LOG_LEN = 10

# A probe result that says something about the HOST rather than about our
# circuit. Everything else is a Tor-side accident and must not be counted as
# evidence that the forum is dead.
_HOST_ANSWERED = frozenset({"guest_open", "login_required", "blocked", "up"})
# Outcomes worth asking again. `unknown` and `unreachable` are almost always
# a dropped circuit, not a dead board.
RETRY_STATUSES = frozenset({"", "unknown", "unreachable", "error", "timeout"})

# Verdicts that are ABOUT THE HOST and can nevertheless go stale.
#
# `blocked` means the host answered and put a challenge in the way — real
# information, unlike a dropped circuit. It was therefore treated as final,
# and the consequence: **a large share of entries marked `blocked` (27 of 70
# in one sweep) answered normally when asked by hand.** Marked once, they
# were excluded from every re-check since and silently dropped from the
# searchable set. Nobody would ever have noticed, because the entry
# looks decided rather than unchecked.
#
# A challenge is a configuration, and configurations change — in both
# directions. So `blocked` is re-asked, but not forever: once the probe log
# says the same thing BLOCKED_CONFIRM_PROBES times, it is a settled verdict
# and the sweep stops spending Tor circuits on it. That is the difference
# between "we never checked" and "we checked three times".
STALE_VERDICTS = frozenset({"blocked"})
BLOCKED_CONFIRM_PROBES = 3


def is_retryable(status: str, probe_log: str = "") -> bool:
    """Should this entry be asked again on a re-check sweep?

    Two different reasons, and keeping them apart is the point:

      * a circuit accident (`unreachable`, `timeout`, …) — always ask again,
        it says nothing about the board;
      * a stale verdict (`blocked`) — ask again until the answer has been
        confirmed BLOCKED_CONFIRM_PROBES times, then let it rest.

    An operator who wants to re-ask a settled verdict anyway uses
    `force_verdicts` on the endpoint; the button says what it does.
    """
    st = str(status or "")
    if st in RETRY_STATUSES:
        return True
    if st in STALE_VERDICTS:
        parts = [p for p in _clean_log(probe_log).split(",") if p]
        confirmations = sum(1 for p in parts if p == st)
        return confirmations < BLOCKED_CONFIRM_PROBES
    return False


def _clean_log(raw) -> str:
    """Normalise a stored probe log to `a,b,c` with at most PROBE_LOG_LEN."""
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw]
    else:
        parts = [p.strip() for p in str(raw or "").split(",")]
    parts = [p[:20] for p in parts if p]
    return ",".join(parts[-PROBE_LOG_LEN:])


def append_probe(log: str, status: str) -> str:
    """Append one outcome, keeping the newest PROBE_LOG_LEN."""
    if not status:
        return _clean_log(log)
    parts = [p for p in _clean_log(log).split(",") if p]
    parts.append(str(status)[:20])
    return ",".join(parts[-PROBE_LOG_LEN:])


def probe_summary(log: str) -> dict:
    """Turn a probe log into the numbers a decision can be made on.

    This is the whole point of keeping a history. A single Tor probe is a
    statement about one circuit at one moment — it must never be used as a
    filter. Entries sitting at `unreachable` after a full sweep are
    overwhelmingly `ProxyError`, i.e. dropped circuits, not dead boards. The
    same host has been observed flipping between `unreachable` and `blocked` between two runs on
    the same day.

    Ten probes turn that unusable yes/no into "answered 3 of 10", which IS
    something you can rank and filter on — and which correctly separates a
    board that is merely hard to reach from one that is gone.
    """
    parts = [p for p in _clean_log(log).split(",") if p]
    answered = sum(1 for p in parts if p in _HOST_ANSWERED)
    return {
        "probes": len(parts),
        "answered": answered,
        # None rather than 0.0 when nothing was probed: "never asked" and
        # "asked ten times, never answered" are different facts, and a 0.0
        # would present the first as the second.
        "rate": round(answered / len(parts), 2) if parts else None,
        "last": parts[-1] if parts else "",
    }


def _settings_url() -> str:
    return f"{settings.license_server_url}/api/v1/platform-settings"


def _headers() -> dict[str, str]:
    # `internal_secret`, not `internal_key`: the former falls back to the
    # global secret when no dedicated internal key is set. The raw field
    # would send an empty header on any install that has not split its
    # secrets yet — a silent 401 on every save.
    return {"X-Internal-Key": settings.internal_secret}


async def get_forums(force: bool = False) -> list[dict]:
    """Everything the operator stores, enabled or not.

    Degrades to an empty list on any failure: module-forums then uses its
    bundled list rather than the search dying because the license-server
    hiccuped.
    """
    now = time.time()
    if not force and "f" in _cache and now - _cache["f"][0] < _TTL:
        return _cache["f"][1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(STORE_KEY)
        items = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
        if not isinstance(items, list):
            items = []
        items = [normalize(f) for f in items if isinstance(f, dict)]
        items = [f for f in items if f["domain"]]
    except Exception as e:  # noqa: BLE001
        log.warning("crime forum list unavailable (%s) — module defaults apply", e)
        items = []
    _cache["f"] = (now, items)
    return items


# Sources whose entries a human picked deliberately. `builtin` is the curated
# list that ships with the runner, `manual` is what the operator typed into the
# panel — and typing a domain in by hand is normally an urgent act, because the
# reason to do it is that a forum has just reappeared under a new address.
_CURATED_SOURCES = frozenset({"builtin", "manual"})

# Hunt tiers. Lower sorts first; see `hunt_order` for what each one means.
_TIER_CURATED = 0
_TIER_INDEXED = 1
_TIER_UNKNOWN = 2
_TIER_EMPTY = 3


def family_of(domain: str) -> str:
    """The registrable name without its TLD: `breachforums.st` → `breachforums`.

    Crime forums run their board on many TLDs at once — the pool holds 16
    `breachforums.*`, 9 `rutor.*`, 6 `darkforums.*` — and the mirrors serve
    substantially the same content. They are worth *storing* separately,
    because which one is up changes weekly, but they are not worth 16 separate
    search-engine queries out of a budget of 40.

    Deliberately a plain second-level label rather than a public-suffix lookup:
    the alternative is shipping and refreshing the PSL inside the api image for
    a value that only ever decides an ORDER. A `co.uk`-style host would group as
    `co`, which costs that host a slot or two and nothing else. The pool holds
    none today, and the check is one line in `test_crime_forum_order.py`.
    """
    parts = str(domain or "").split(".")
    return parts[-2] if len(parts) >= 2 else str(domain or "")


def _tier(forum: dict) -> int:
    """Which band a forum sorts into.

    `not_indexed` outranks nothing: the hunt asks a search engine `site:<host>`,
    so a host the engine has nothing for cannot return a hit no matter how alive
    it is. That is arithmetic, not a judgement, and it applies to a curated
    entry too — a forum that has dropped out of the index has stopped being
    reachable *by this tool*, whoever vouched for it.

    Everything above that band is ordered by who chose it, NOT by how much the
    engine has. `index_count` deliberately does not appear here: measured
    across all clearnet entries of the pool, it ranks openness, and openness
    runs *against* relevance for exactly the forums that matter — `xss.is`
    scores 6 and `exploit.in` 9 because they sit behind a login wall, while
    `lowendtalk.com` (VPS hosting) and `forum.dangerousthings.com` (biohacking)
    max out the 20-hit sample. Sorting by it would drop the two most important
    Russian crime forums in favour of hobbyist boards.
    """
    if forum.get("index_status") == IDX_NOT_INDEXED:
        return _TIER_EMPTY
    if forum.get("source") in _CURATED_SOURCES:
        return _TIER_CURATED
    if forum.get("index_status") == IDX_INDEXED:
        return _TIER_INDEXED
    return _TIER_UNKNOWN


def hunt_order(items: list[dict]) -> list[dict]:
    """Order the forums so that truncating the list keeps the useful ones.

    The runner caps the hunt at `CRIME_FORUM_MAX` (40) because every enabled
    forum costs one search-engine query per search, and the Brave free tier is
    ~2 000 a month — 272 enabled forums would be one hunt per four days. The cap
    is sound; how it used to bite was not. It took `all_forums[:40]`, i.e. the
    list in STORAGE order, which after a deepdarkCTI import is the curated
    entries followed by hundreds of imports **alphabetically**. In practice
    that spent 5 of the 40 slots on `bhf.ee/.gg/.im/.io/.pro`
    — five mirrors of one board — and cut off mid-"b", so the entire
    BreachForums family, the strongest cluster in the pool, was never queried.

    Two rules, in this order:

    1. **Band** (`_tier`) — curated first, then imports the engine has
       something for, then imports nobody has checked, then the ones checked
       and found empty.
    2. **One mirror per family before any family's second** — `family_of`
       groups `breachforums.st` with `breachforums.ac`, and the round-robin
       means the widest-mirrored board can no longer crowd out 15 others.

    **What this deliberately does NOT do is rank the imports by quality**, and
    that limit is the honest one: 260 of them arrived uncategorised, and no
    measurement in this system tells crime relevance apart (see `_tier` on why
    `index_count` is the wrong signal). Within a band the order is therefore the
    domain name, and the only real answer to "which 40" stays curation in the
    panel. This function makes the cap *fair*; it cannot make it *smart*.

    Pure and synchronous so the ordering is testable without a license-server.
    """
    # Rank inside the family on a fully determined order, so the member that
    # represents a family is stable across calls rather than dependent on how
    # the store happened to serialise the list.
    ranked = sorted(items, key=lambda f: (_tier(f), f["domain"]))
    seen: dict[str, int] = {}
    spread: list[tuple[int, int, str, dict]] = []
    for f in ranked:
        fam = family_of(f["domain"])
        nth = seen.get(fam, 0)
        seen[fam] = nth + 1
        spread.append((_tier(f), nth, f["domain"], f))
    spread.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in spread]


async def get_active_domains(force: bool = False) -> list[str]:
    """Clearnet hosts that should actually be dorked, best-first.

    Onion entries are excluded here on purpose: the clearnet dork asks a
    search engine, and no clearnet index carries a hidden service. Sending
    them would spend one query per onion to reliably find nothing — and
    worse, would eat into the per-hunt cap that the operator's real dork
    targets need.

    **Order matters and is decided here**, not in the module: the module is
    handed a list of bare host names and has no way to tell a curated entry
    from an import or an indexed host from an empty one. It caps at
    `CRIME_FORUM_MAX` and reports what it left out — so whichever forums this
    function puts first are the ones a capped hunt actually queries. See
    `hunt_order`.

    Returned to the orchestrator, which passes them to the module. An empty
    result deliberately means "module, use your own list" — never "search
    nothing", because a license-server hiccup must not silently reduce a
    hunt's coverage to zero.
    """
    return [f["domain"] for f in hunt_order(
        [f for f in await get_forums(force)
         if f["enabled"] and f["surface"] == SURFACE_CLEARNET])]


async def get_active_onions(force: bool = False) -> list[dict]:
    """Known onion forums, for the Tor half of the hunt.

    Not a search target but a **recognition table**: the darknet sweep
    already discovers onion hosts for a handle, and it used to report every
    one of them as an anonymous `onion_service`. Matching them against this
    list turns "some hidden service mentions this handle" into "the hidden
    service of BreachForums mentions this handle", which is the difference
    between a lead and a citation.

    Carries the name and category, not just the host, because that is what
    makes the finding readable.
    """
    return [{"domain": f["domain"], "name": f["name"], "category": f["category"]}
            for f in await get_forums(force)
            if f["enabled"] and f["surface"] == SURFACE_ONION]


async def save_forums(items: list[dict]) -> list[dict]:
    """Replace the stored list. Returns the normalized list that was saved."""
    clean: list[dict] = []
    seen: set[str] = set()
    for f in items:
        if not isinstance(f, dict):
            continue
        n = normalize(f)
        if not n["domain"] or n["domain"] in seen:
            continue
        seen.add(n["domain"])
        clean.append(n)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.put(_settings_url(), headers=_headers(),
                             json={"values": {STORE_KEY: json.dumps(clean)}})
        r.raise_for_status()
    _cache.pop("f", None)
    return clean


def parse_bulk(text: str, category: str = "other",
               source: str = "manual", enabled: bool = True) -> list[dict]:
    """Turn pasted text into forum records.

    Accepts whatever an analyst actually has in the clipboard: one per line,
    comma separated, bare domains or full URLs, with `#` comments. Anything
    that is not a plausible host name is dropped rather than stored as a
    forum that every search then queries for nothing.

    Unlike the Telegram import, manual additions default to **enabled**: an
    operator typing a domain into this box has picked it deliberately, and
    the pool here is a dozen entries rather than a thousand.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        line = line.split("#", 1)[0]
        for token in re.split(r"[,;\s]+", line):
            d = normalize_domain(token)
            if d and d not in seen:
                seen.add(d)
                out.append(normalize({"domain": d, "category": category,
                                      "source": source, "enabled": enabled}))
    return out


# ── deepdarkCTI import ───────────────────────────────────────────────

DDCTI_FORUMS_URL = ("https://raw.githubusercontent.com/fastfire/deepdarkCTI/"
                    "main/forum.md")

# `| [Name](url) | STATUS |` — the shape of that file's markdown table.
_DDCTI_ROW = re.compile(
    r"\|\s*\[([^\]]+)\]\((https?://[^)\s]+)\)\s*\|\s*(\w+)")


async def fetch_deepdarkcti() -> tuple[list[dict], dict]:
    """Harvest forum hosts from deepdarkCTI's `forum.md`.

    Returns `(records, stats)`. Records arrive **disabled** — the file
    yields well over a hundred clearnet hosts alone, and the hunt spends
    one search-engine query per ENABLED forum against a cap of 40. Importing
    them active would not search more; it would make every hunt slow and
    then silently truncate.

    **The upstream ONLINE/OFFLINE column is kept as a note, never as a
    filter.** It is community-maintained and it lags: that file lists
    `xss.is` as OFFLINE while a Tor probe at the same time got HTTP 200 and
    the genuine XSS login page. Filtering on it would have
    dropped a live forum on someone else's stale claim — which is exactly
    what the framework's own index/reach checks exist to avoid.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(DDCTI_FORUMS_URL)
        r.raise_for_status()
        text = r.text

    out: dict[str, dict] = {}
    stats = {"rows": 0, "clearnet": 0, "onion": 0, "unusable": 0,
             "by_status": {}}
    for name, url, status in _DDCTI_ROW.findall(text):
        stats["rows"] += 1
        st = status.upper()
        stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
        host = normalize_domain(url)
        if not host:
            stats["unusable"] += 1
            continue
        if host in out:
            continue
        rec = normalize({
            "domain": host,
            "name": name.strip(),
            "category": "darknet" if surface_of(host) == SURFACE_ONION else "other",
            "source": "deepdarkcti",
            "enabled": False,
            "note": f"deepdarkCTI: {name.strip()} [{st}]"[:200],
        })
        out[host] = rec
        stats["onion" if rec["surface"] == SURFACE_ONION else "clearnet"] += 1
    return list(out.values()), stats


def default_records(enabled: bool = True) -> list[dict]:
    """The runner's built-in list as store records."""
    return [normalize({"domain": d, "category": c, "source": "builtin",
                       "enabled": enabled}) for d, c in DEFAULT_FORUMS]


# ── health check ─────────────────────────────────────────────────────
#
# Two questions, kept apart because they have different answers and
# different consequences (the module's `forum_check.py` explains the probes
# themselves):
#
#   index — has the search engine indexed anything of this forum? This is
#           what decides whether the forum can contribute to a hunt at all,
#           because the hunt asks a search engine and never fetches the
#           forum. Costs no contact with the host.
#   reach — is the host answering, asked over Tor? Context only: it
#           separates "dead" from "alive but closed to us".
#
# A forum can be busy and alive and still be worth nothing here — that is
# the normal case for a login-walled forum, not an anomaly.

IDX_NOT_INDEXED = "not_indexed"
IDX_INDEXED = "indexed"


async def check_forums(domains: list[str], mode: str = "index") -> dict[str, dict]:
    """Run the probes in module-forums and return `{domain: result}`.

    The Brave key travels in `options.credentials`, exactly as it does for a
    normal tool run, so a key saved in the panel takes effect with no
    restart and the module never talks to the key store itself.
    """
    from app.services.api_keys import load_keys

    try:
        creds = await load_keys()
    except Exception:  # noqa: BLE001 — a key-store hiccup must not kill the check
        creds = {}
    url = f"{settings.module_forums_url}/forum-check"
    # Tor is slow and the module probes concurrently; this ceiling is for the
    # whole batch, not per host. `access` makes TWO Tor requests per host
    # against boards that routinely sit behind a challenge, so the same ceiling
    # would abort a batch the module was still working through — and an aborted
    # batch writes nothing at all, which is worse than a slow one.
    budget = 900 if mode == "access" else 300
    async with httpx.AsyncClient(timeout=budget) as client:
        r = await client.post(url, json={
            "domains": domains, "mode": mode,
            "options": {"credentials": creds},
        })
        r.raise_for_status()
        return (r.json() or {}).get("results") or {}


async def apply_check(results: dict[str, dict]) -> list[dict]:
    """Write probe results onto the stored forums.

    Only the keys a probe actually produced are written: an `index`-only run
    must not blank out a reachability result from an earlier `reach` run, or
    the column would flicker between "checked" and "never checked" depending
    on which button was pressed last.

    The two host-touching probes also APPEND to their log rather than only
    overwriting the current value — see `probe_summary` for why one result
    cannot carry the decision.
    """
    items = await get_forums(force=True)
    for f in items:
        res = results.get(f["domain"])
        if not res:
            continue
        for field, logfield in (("reach_status", "reach_log"),
                                ("access_status", "access_log")):
            status = res.get(field)
            if status:
                f[logfield] = append_probe(f.get(logfield, ""), status)
        f.update({k: v for k, v in res.items() if v is not None})
    return await save_forums(items)


def merge(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int]:
    """Add what is new, keep what the operator decided.

    Returns (merged, added). An incoming domain that is already stored does
    NOT reset its `enabled` flag, note or category — re-seeding the defaults
    must never silently re-enable a forum somebody switched off, nor undo a
    re-categorisation.
    """
    by_domain = {f["domain"]: f for f in existing}
    added = 0
    for f in incoming:
        if f["domain"] in by_domain:
            continue
        by_domain[f["domain"]] = f
        added += 1
    return list(by_domain.values()), added
