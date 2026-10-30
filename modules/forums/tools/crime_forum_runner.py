"""
Crime-forum username hunt (clearnet + darknet, keyless).

Answers "where does this username / handle show up in cybercrime forums?"
across both surfaces:

  * Clearnet: a curated crime-forum list is dorked via DuckDuckGo
    (`site:<forum> "<username>"`) → real profile/thread links.
  * Darknet: the username is searched on Tor engines (Torch, TorDex)
    through the bundled Tor SOCKS proxy → onion forums/markets mentioning
    it.

Both are keyless. Direct per-forum account enumeration (login-walled) is
intentionally out of scope — that needs a paid forum-intel API and is a
later, key-gated upgrade.

**The forum list has three sources**, in priority order (see `_forums`):
the operator's list from the Owner console (`options.forums`), the
`CRIME_FORUMS` env var, and the bundled `_DEFAULT_FORUMS`. Crime forums are
seized and reborn under new domains several times a year, which is a cadence
no redeploy keeps up with — so the console is the one place that decides,
and it takes effect on the next search without restarting anything.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from onion_blacklist import screen_hosts
from schemas import EdgeResult, Finding, NOTE_PREFIX, credential
from tools.forum_check import HIT_PROFILE, classify_url

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
              "Gecko/20100101 Firefox/115.0")
DDG_HTML = "https://html.duckduckgo.com/html/"
BRAVE_API = "https://api.search.brave.com/res/v1/web/search"
TOR_PROXY = os.getenv("TOR_SOCKS_PROXY", "").strip()

# Curated, commonly-active cybercrime / hacking / leak forums (clearnet).
# Override/extend with CRIME_FORUMS="a.com,b.is" in the env.
_DEFAULT_FORUMS = [
    "xss.is", "exploit.in", "nulled.to", "cracked.io", "cracked.sh",
    "hackforums.net", "sinister.ly", "leakzone.net", "breachforums.st",
    "ogusers.gg", "leakbase.io", "blackhatworld.com",
]
MAX_PER_FORUM = 3
# A keyword search asks a different question than a handle search. "Is this
# account here" is answered by the first hits; "what is being said about this
# topic" is not — three threads per board is a keyhole. Costs nothing extra:
# the count is one parameter of the SAME query, not more queries.
MAX_PER_FORUM_KEYWORD = int(os.getenv("CRIME_FORUM_HITS_KEYWORD", "10") or 10)
# Both darknet engines render results as `<div class="result">`. Parsing the
# blocks rather than the page is what keeps advertising out of the case file —
# see `_tor_search`.
TOR_RESULT_SELECTOR = ".result"
# One search-engine query per forum, all fired concurrently. The bundled list
# is 12 entries, but the operator list is free-form and a paste of 300 domains
# would turn one hunt into 300 API calls — enough to burn a Brave quota or earn
# a block. Capped here, and, as everywhere in this stack, what was left out is
# reported rather than silently dropped.
MAX_FORUMS = int(os.getenv("CRIME_FORUM_MAX", "40") or 40)

# Wall-clock budget for ONE run, deliberately BELOW the orchestrator's 300 s
# cut for a `slow` tool. That gap is the whole point: when the caller's
# timeout fires it discards everything this tool found, and the investigator
# is told the module was unreachable. Finishing inside the budget turns the
# same stall into a partial result plus a note saying what was skipped.
#
# Why it is needed at all: a normal run over a large configuration (a few
# hundred forums, dozens of onions) takes seconds, and every individual
# request here is bounded (25 s clearnet, 60 s per Tor engine, 20 s for the
# blacklist). Yet a run can still sit until the outer 300 s cut and be
# killed from outside. Per-request timeouts do not bound a phase that
# keeps trickling — over Tor that is a normal condition, not a fault — so
# the run needs a ceiling of its own.
RUN_BUDGET = float(os.getenv("CRIME_FORUM_BUDGET", "240") or 240)
ONION_RE = re.compile(r"([a-z2-7]{56}|[a-z2-7]{16})\.onion")

TOR_ENGINES = [
    ("torch", "http://torchdeedp3i2jigzjdmfpn5ttjhthh5wbmda2rr3jvqjg5p77c54dqd.onion/search", "query"),
    ("tordex", "http://tordexu73joywapk2txdr54jed4imqledpcvcuf75qsas2gwdgksvnyd.onion/search", "query"),
]
TOR_ENGINE_HOSTS = {
    "torchdeedp3i2jigzjdmfpn5ttjhthh5wbmda2rr3jvqjg5p77c54dqd.onion",
    "tordexu73joywapk2txdr54jed4imqledpcvcuf75qsas2gwdgksvnyd.onion",
}

log = logging.getLogger("module-forums.crime_forum")


def _forums(options: dict | None = None) -> list[str]:
    """The domains to dork, in priority order.

      1. ``options.forums`` — the list the operator maintains in the Owner
         console, handed over per run. When present it is used ALONE: the
         console is then the single place that decides what gets dorked, and
         silently mixing in a stale env value would make the panel's forum
         count a lie. Same rule as module-messenger's ``options.channels``.
      2. ``CRIME_FORUMS`` env (comma separated) — quick override without a
         console, kept so existing deployments behave exactly as before.
      3. ``_DEFAULT_FORUMS`` — the bundled list, so a fresh install still
         hunts something sensible on day one.

    Deduplicated, order preserved: the operator's ordering survives to the
    cap, so the entries they care about are the ones that make the cut.
    """
    supplied = [str(f).strip().lower()
                for f in ((options or {}).get("forums") or []) if str(f).strip()]
    if supplied:
        raw = supplied
    else:
        env = os.getenv("CRIME_FORUMS", "").strip()
        raw = ([f.strip().lower() for f in env.split(",") if f.strip()]
               if env else list(_DEFAULT_FORUMS))
    seen: set[str] = set()
    out: list[str] = []
    for f in raw:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _unwrap_ddg(href: str) -> str:
    # DDG HTML wraps external links as //duckduckgo.com/l/?uddg=<url>
    if "duckduckgo.com/l/" in href:
        qs = urllib.parse.urlparse(href).query
        u = urllib.parse.parse_qs(qs).get("uddg")
        if u:
            return u[0]
    return href if href.startswith("http") else f"https:{href}"


class _Blocked(Exception):
    """Search engine returned an anti-bot page (datacenter IP blocked)."""


def _clean(text: str, limit: int) -> str:
    """Search engines mark the matched term with <strong>; strip the markup and
    collapse the whitespace so an excerpt is readable in a node card and in the
    PDF without carrying HTML into the case file."""
    if not text:
        return ""
    return " ".join(re.sub(r"<[^>]+>", "", str(text)).split())[:limit]


async def _brave_dork(client: httpx.AsyncClient, forum: str, username: str,
                      key: str, per_forum: int) -> list[dict]:
    """One `site:` query, and everything the answer carries.

    The API returns 17 fields per result and this used to keep two (title,
    url). The excerpt and the post date were paid for by the same call and
    thrown away — while "what does this account actually post" was the
    question the tool exists to answer. They cost no extra quota, no extra
    latency and, decisively, **no contact with the forum**: this is the search
    engine's own record of a public page, not content we fetched.
    """
    q = f'site:{forum} "{username}"'
    r = await client.get(BRAVE_API, params={"q": q, "count": str(per_forum)},
                         headers={"X-Subscription-Token": key,
                                  "Accept": "application/json"})
    if r.status_code in (401, 403):
        raise _Blocked(f"Brave HTTP {r.status_code}")
    if r.status_code != 200:
        return []
    out: list[dict] = []
    for res in (r.json().get("web", {}) or {}).get("results", [])[:per_forum]:
        url = res.get("url", "")
        if forum not in url:
            continue
        extra = [_clean(s, 300) for s in (res.get("extra_snippets") or [])[:3]]
        out.append({
            "title": _clean(res.get("title"), 160),
            "url": url,
            "snippet": _clean(res.get("description"), 400),
            "extra_snippets": [s for s in extra if s],
            # When the engine dates the page. Feeds the report timeline and is
            # what separates "posted last week" from "posted in 2016".
            "posted": _clean(res.get("age") or res.get("page_age"), 40),
        })
    return out


async def _ddg_dork(client: httpx.AsyncClient, forum: str, username: str,
                    per_forum: int) -> list[dict]:
    q = f'site:{forum} "{username}"'
    r = await client.post(DDG_HTML, data={"q": q})
    # DDG serves an anti-bot challenge (HTTP 202) to datacenter IPs.
    if r.status_code != 200 or "challenge" in r.text.lower():
        raise _Blocked(f"DDG HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.select(".result__a"):
        url = _unwrap_ddg(a.get("href", ""))
        if forum not in url or url in seen:
            continue
        seen.add(url)
        # The excerpt sits in a sibling of the link, inside the same result
        # block — read from the block, never from the page, so navigation and
        # ad slots cannot become an excerpt.
        block = a.find_parent(class_="result") or a.find_parent()
        snip = ""
        if block is not None:
            el = block.select_one(".result__snippet")
            snip = _clean(el.get_text(" ", strip=True) if el else "", 400)
        out.append({"title": _clean(a.get_text(strip=True), 160), "url": url,
                    "snippet": snip, "extra_snippets": [], "posted": ""})
        if len(out) >= per_forum:
            break
    return out


async def _dork_forum(client: httpx.AsyncClient, forum: str, username: str,
                      brave_key: str, per_forum: int) -> list[dict]:
    """Prefer the robust Brave Search API (key); fall back to keyless DDG
    (best-effort — often blocked from a server). Raises _Blocked when the
    engine refuses so the caller can surface one clear note."""
    if brave_key:
        return await _brave_dork(client, forum, username, brave_key, per_forum)
    return await _ddg_dork(client, forum, username, per_forum)


async def _tor_search(username: str) -> tuple[dict[str, dict], list[str]]:
    """Search the darknet engines and return `{host: {...}}` plus any notes.

    ⚠️ **Read the RESULT BLOCKS, never every link on the page.** Walking
    `find_all("a")` and keeping any `.onion` seen means, on a Torch result
    page, 78 hosts of which 14 are results. The other 64
    are navigation and **paid banners** — measured on the term "ransomware",
    the 20 emitted findings included `Images`, `Tags`, `TORMART - MARKETPLACE`,
    `Cash2Tor`, `PRIME MARKET`, an `E-MARKET` selling MDMA and cocaine, and a
    sex-tape site. Every one of them would arrive in the case graph as an
    `onion_service` joined to the investigated selector by a `forum_onion_match`
    edge — the graph would assert a relationship between a suspect's handle and a
    drug market that exists only because somebody bought advertising on Torch.
    In an evidentiary file that is not noise, it is a false statement, and it
    is the kind that discredits the findings around it.

    Both engines render `<div class="result">` with `h5#title`, `h6#link` and
    `p#desc`, so one selector covers them. **No fallback to link-scraping**: if
    an engine changes its layout the run says so and returns nothing from it.
    Guessing would silently restore exactly the defect above.

    ⚠️ **Everything that leaves here is screened against Ahmia's abuse
    blacklist** (`onion_blacklist.screen_hosts`). Originally it was not:
    the two darknet-module tools screened their onion hits and this path,
    querying the very same engines over the very same proxy, did not — because
    the screening lived inside the darknet module and could not be imported.
    A keyword hunt could therefore attach a blacklisted hidden service to the
    investigated selector, and it would travel from the graph into the PDF
    report. Withheld hits are reported as a note, never dropped in silence.
    """
    if not TOR_PROXY:
        return {}, []
    hosts: dict[str, dict] = {}
    notes: list[str] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    async with httpx.AsyncClient(proxy=TOR_PROXY, timeout=60, headers=headers,
                                 follow_redirects=True) as client:
        for name, url, param in TOR_ENGINES:
            try:
                r = await client.get(url, params={param: username})
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                log.info("tor engine %s failed: %s", name, e)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            blocks = soup.select(TOR_RESULT_SELECTOR)
            if not blocks:
                notes.append(f"{NOTE_PREFIX}darknet engine '{name}' returned no "
                             f"parsable result blocks — layout may have changed; "
                             f"its results were skipped rather than guessed at.")
                continue
            for block in blocks:
                link = block.select_one("h5 a[href], a[href]")
                if link is None:
                    continue
                href = link.get("href", "")
                m = ONION_RE.search(href)
                if not m:
                    continue
                host = m.group(0).lower()
                if host in TOR_ENGINE_HOSTS:
                    continue
                desc = block.select_one("p")
                hit = {
                    "url": href[:400],
                    "title": _clean(link.get_text(" ", strip=True), 160),
                    "snippet": _clean(desc.get_text(" ", strip=True) if desc else "", 400),
                }
                # The onion HOST is the node identity, but a board can match on
                # several pages and the thread link is what an investigator
                # opens. Keep the first as the node's url and collect the rest.
                entry = hosts.setdefault(host, {**hit, "hits": []})
                if len(entry["hits"]) < MAX_PER_FORUM:
                    entry["hits"].append(hit)

        # Screen before returning, so no caller can forget it. The blacklist
        # itself is a clearnet file; fetching it through the Tor client is
        # harmless and keeps this to one client.
        hosts, screen_notes = await screen_hosts(client, hosts)
        notes.extend(screen_notes)
    return hosts, notes


# Contact/crypto identifiers hunted the same way a username is (actors
# advertise their Jabber/Tox/Session ID on the same crime forums). The
# root node keeps the selector's own type so the graph shows e.g. a
# `jabber_id` node fanning out to forum hits.
_CONTACT_TYPES = {"jabber_id", "tox_id", "session_id"}


def _term_and_root(query: str, query_type: str) -> tuple[str, str]:
    raw = (query or "").strip()
    if query_type == "username":
        term = raw.lstrip("@")
        return term, f"username:{term.lower()}"
    if query_type in _CONTACT_TYPES:
        return raw, f"{query_type}:{raw.lower()}"
    # keyword / anything else — search the literal term
    return raw, f"keyword:{raw.lower()}"


async def run_crime_forum_hunt(
    query: str, query_type: str = "username", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term, root = _term_and_root(query, query_type)
    if not term:
        return [], [], ["Crime-forum hunt: empty query"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    # See RUN_BUDGET: the two phases share one wall clock so a stalled phase
    # costs the run its remainder instead of the whole search.
    deadline = time.monotonic() + RUN_BUDGET

    def _left() -> float:
        return max(0.0, deadline - time.monotonic())

    # 1) Clearnet dorks across the curated forum list (concurrent).
    #    Robust with a Brave Search API key; keyless DDG is best-effort and
    #    is usually blocked from a datacenter IP → surfaced as one note.
    brave_key = credential(options, "BRAVE_API_KEY")
    all_forums = _forums(options)
    forums = all_forums[:MAX_FORUMS]
    if len(all_forums) > len(forums):
        errors.append(f"{NOTE_PREFIX}{len(all_forums)} forums configured, "
                      f"searched the first {MAX_FORUMS} (CRIME_FORUM_MAX "
                      f"raises the cap).")
    per_forum = (MAX_PER_FORUM_KEYWORD if query_type not in ("username",)
                 and query_type not in _CONTACT_TYPES else MAX_PER_FORUM)
    async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        try:
            dork_results = await asyncio.wait_for(
                asyncio.gather(
                    *(_dork_forum(client, f, term, brave_key, per_forum)
                      for f in forums),
                    return_exceptions=True,
                ),
                timeout=_left(),
            )
        except asyncio.TimeoutError:
            # The gather is cancelled with the wait_for, so nothing partial
            # survives from it — say so rather than reporting "no hits",
            # which would read as "this handle is on no forum".
            dork_results = []
            errors.append(f"{NOTE_PREFIX}Clearnet forum sweep exceeded the "
                          f"{RUN_BUDGET:.0f}s budget for this tool and was cut "
                          f"off; its results are missing from this run, not "
                          f"empty. The darknet sweep below still ran.")
    blocked = 0
    for forum, res in zip(forums, dork_results):
        if isinstance(res, _Blocked):
            blocked += 1
            continue
        if isinstance(res, Exception) or not res:
            continue
        # What KIND of hit this is. A profile page means the handle is a member
        # of that board; a thread means it was written somewhere on it. Both
        # used to arrive as one undifferentiated `forum_hit` at confidence
        # 0.55, so "has accounts on six forums" and "was named in six threads"
        # read identically — different statements about a person, and only one
        # of them makes them a member.
        kinds = [classify_url(h["url"]) for h in res]
        has_profile = HIT_PROFILE in kinds
        # Raised only for the account case, and only for a handle-shaped query:
        # a profile URL carrying a keyword says nothing about membership.
        conf = 0.7 if (has_profile and query_type not in ("keyword",)) else 0.55
        findings.append(Finding(
            entity_type="forum_hit", platform="clearnet",
            label=f"{term}@{forum}", url=res[0]["url"], confidence=conf,
            data={"forum": forum, "term": term, "query_type": query_type,
                  "surface": "clearnet",
                  "hits": [h["url"] for h in res],
                  "titles": [h["title"] for h in res],
                  # What the matched pages actually SAY, as the search engine
                  # recorded it. The whole point of the finding: an analyst can
                  # triage without opening a crime forum, and the excerpt is a
                  # citable statement about a public page rather than a bare
                  # link that has to be trusted.
                  "excerpts": [{"url": h["url"], "title": h["title"],
                                "snippet": h.get("snippet", ""),
                                "posted": h.get("posted", ""),
                                "extra": h.get("extra_snippets") or []}
                               for h in res],
                  "posted": res[0].get("posted", ""),
                  "hit_kinds": kinds,
                  "has_profile": has_profile,
                  "url": res[0]["url"], "source": "ddg_dork"},
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"forum_hit:{term}@{forum}",
            # The relation carries the difference too, so the graph and the
            # report state it without re-deriving it from the node data.
            relation="member_of" if has_profile else "mentioned_on",
            confidence=conf))

    if blocked and not brave_key:
        errors.append(f"{NOTE_PREFIX}Clearnet forum dorking was blocked "
                      f"({blocked} engines refused this datacenter IP). Set a "
                      "free BRAVE_API_KEY in Global-Admin → Settings for robust "
                      "clearnet search — the darknet (Tor) sweep still ran.")

    # 2) Darknet index (Tor), if the proxy is configured.
    #
    # Known onion forums from the Owner console are a RECOGNITION table, not
    # a search target: nothing here fetches them. Without that table every
    # hit comes back as an anonymous `onion_service` with confidence 0.45, so
    # "some hidden service mentions this handle" and "BreachForums mentions
    # this handle" were the same row. Matching against the operator's list
    # names the second one and rates it higher — a hit on a forum somebody
    # deliberately put on the list is a different statement from a hit on an
    # unknown host.
    known: dict[str, dict] = {}
    for f in ((options or {}).get("onion_forums") or []):
        h = str((f or {}).get("domain") or "").strip().lower()
        if h:
            known[h] = f
    try:
        # Bounded by whatever the clearnet phase left. Every request in here
        # already has its own timeout; what this bounds is the PHASE, which
        # a slow Tor circuit can stretch past all of them together.
        onions, tor_notes = await asyncio.wait_for(_tor_search(term),
                                                   timeout=_left())
        errors.extend(tor_notes)
    except asyncio.TimeoutError:
        onions = {}
        errors.append(f"{NOTE_PREFIX}Darknet (Tor) sweep exceeded the "
                      f"{RUN_BUDGET:.0f}s budget for this tool and was cut "
                      f"off; its results are missing from this run, not empty. "
                      f"Tor was slow — re-running usually succeeds.")
    except Exception as e:  # noqa: BLE001
        onions = {}
        errors.append(f"Tor search failed: {type(e).__name__}")
    matched = 0
    for host, hit in list(onions.items())[:20]:
        forum = known.get(host)
        conf = 0.6 if forum else 0.45
        data = {"onion": host, "title": hit.get("title", ""), "term": term,
                "query_type": query_type,
                "surface": "darknet",
                # The engine's excerpt and the page that actually matched. The
                # host alone said "something on this service mentions the term"
                # and made the investigator go and look; the thread link and the
                # excerpt say what and where.
                "snippet": hit.get("snippet", ""),
                "hits": [h["url"] for h in hit.get("hits", [])],
                "excerpts": hit.get("hits", []),
                "url": hit.get("url") or f"http://{host}",
                "source": "tor_forum_hunt"}
        if forum:
            matched += 1
            data.update({
                "known_forum": True,
                "forum_name": forum.get("name") or "",
                "forum_category": forum.get("category") or "",
            })
        findings.append(Finding(
            entity_type="onion_service", platform="tor",
            # The label stays the onion host — it is the node's identity and
            # the edge endpoint. The human-readable name lives in `data`, or
            # two spellings of one service would become two nodes.
            # The url points at the page that MATCHED, not at the service root:
            # the root is where the investigator had to start searching again by
            # hand, the matched page is the evidence. The host remains the
            # identity, so this does not split the node.
            label=host, url=data["url"], confidence=conf,
            data=data,
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"onion_service:{host}",
            # A different relation for a recognised forum, so the graph shows
            # WHY this node matters instead of burying it among the rest.
            relation="known_forum_match" if forum else "forum_onion_match",
            confidence=conf))

    if known:
        errors.append(f"{NOTE_PREFIX}{len(known)} known onion forum(s) from the "
                      f"operator list used for recognition; {matched} of the "
                      f"darknet hits matched one. They are not fetched — the "
                      f"list names hits, it does not search them.")

    if not findings and not errors:
        errors.append(f"No crime-forum hits for '{term}'")
    return findings, edges, errors
