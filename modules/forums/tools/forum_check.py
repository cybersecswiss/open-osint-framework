"""Health check for the operator's crime-forum list.

Answers the two questions an operator actually has about a forum on their
list, and keeps them apart, because they have different answers and
different consequences:

**1. Is anything readable from it?** — the `index` probe.
This is the one that decides whether a forum is worth its slot. The hunt
never fetches a forum: it asks a search engine `site:<domain> "<handle>"`.
So a forum contributes exactly as much as the search engine has indexed of
it — and a forum can be perfectly alive, wildly active, and still yield
NOTHING here, because its content sits behind a login wall, a robots.txt or
a bot defence the crawler never got past. `site:<domain>` with no handle
measures precisely that, and it does so **without ever contacting the
forum**.

**2. Is it up at all?** — the `reach` probe.
Context for the first answer: it separates "dead" from "alive but closed".
This one DOES contact the host, so it goes **through Tor** — the framework
must not connect to crime forums from the operator's own address.

Neither status is ever dressed up as more than it is:

* `not_indexed` does not mean "dead". It means this tool cannot get
  anything out of it, which is the operationally relevant statement.
* `blocked` does not mean "down". Cloudflare and DDoS-Guard answer a bare
  request with 403 or a challenge page — several forums on the default list
  do exactly that, and they are still the interesting ones.
* `unreachable` over Tor does not mean "offline" either: an exit-side
  failure and a dead host are indistinguishable from here. Same rule as the
  Telegram panel's `no_public_page`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

import httpx

# curl_cffi speaks a real browser's TLS/JA3 fingerprint. Optional on purpose:
# if the wheel is missing the module still runs, it just loses the retry.
try:                                     # pragma: no cover - import shape
    from curl_cffi.requests import AsyncSession as _CurlSession
    HAVE_CURL = True
except Exception:                        # noqa: BLE001
    _CurlSession = None
    HAVE_CURL = False

from schemas import credential


def is_onion(host: str) -> bool:
    return str(host or "").lower().endswith(".onion")

log = logging.getLogger("module-forums.check")

TOR_PROXY = os.getenv("TOR_SOCKS_PROXY", "").strip()
BRAVE_API = "https://api.search.brave.com/res/v1/web/search"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
              "Gecko/20100101 Firefox/115.0")

CHECK_CONCURRENCY = int(os.getenv("FORUM_CHECK_CONCURRENCY", "6") or 6)
# Tor adds latency on top of whatever the host does. Generous, because a
# timeout here would be reported as "unreachable" — a wrong statement about
# the forum caused by our own impatience.
REACH_TIMEOUT = int(os.getenv("FORUM_CHECK_TIMEOUT", "45") or 45)

# What Brave is asked for. The number returned is a FLOOR, not a page count:
# we ask for 20 and report what came back, so 20 means "at least 20".
INDEX_SAMPLE = 20

# --- index statuses ---
IDX_INDEXED = "indexed"
IDX_NOT_INDEXED = "not_indexed"
IDX_NO_KEY = "no_key"
IDX_ERROR = "error"
# An onion is not "un-indexed" — no clearnet search engine indexes hidden
# services at all, so the question does not apply. Reporting `not_indexed`
# would be a category error that reads as a defect, and would feed the
# "disable un-indexed" cleanup a list of perfectly good onion forums.
IDX_NOT_APPLICABLE = "not_applicable"

# --- reachability statuses ---
REACH_ONLINE = "online"
REACH_BLOCKED = "blocked"          # up, but refuses us (WAF / challenge)
REACH_UNREACHABLE = "unreachable"  # no answer — NOT the same as "offline"
REACH_NO_TOR = "no_tor"
REACH_ERROR = "error"

# Bot-defence fingerprints. Matched on the body because the status code alone
# lies in both directions: DDoS-Guard serves its interstitial with HTTP 200,
# and some forums answer 403 to a HEAD but 200 to a normal GET.
_CHALLENGE_MARKERS = (
    "just a moment", "checking your browser", "cf-browser-verification",
    "cf_chl_opt", "ddos-guard", "ddosguard", "attention required",
    "enable javascript and cookies", "__cf_bm", "sucuri_cloudproxy",
    # Measured: exploit.in answers HTTP 200 with a "Verify
    # Humanity" interstitial, i.e. a challenge that carries none of the
    # Cloudflare markers above. Without these it was reported as `online`,
    # which reads as "we can work with this" — the opposite of the truth.
    "verify humanity", "verifying you are human", "one moment, please",
    "please wait while we verify", "checking if the site connection is secure",
)
_TITLE_RE = re.compile(r"<title[^>]*>(.{0,120}?)</title>", re.I | re.S)
_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']{0,60})', re.I)

# --- access statuses (the `access` probe) ---
ACC_OPEN = "guest_open"          # member area readable without an account
ACC_LOGIN = "login_required"     # answered, and demanded an account
ACC_BLOCKED = "blocked"          # bot defence answered instead of the forum
ACC_UNREACHABLE = "unreachable"  # no answer — NOT "offline", same rule as reach
ACC_UNKNOWN = "unknown"          # answered, but nothing decidable came back
ACC_NO_TOR = "no_tor"

# Forum software → where the member area lives, and whether a single account
# can be checked by name. The distinction is not cosmetic: XenForo, SMF and
# vBulletin address a profile by NUMERIC id, so `/members/<handle>` cannot be
# probed for existence at all, while MyBB, phpBB, Discourse and Flarum take the
# name. Only the latter can ever support a per-handle account check, and saying
# so per forum is what stops that feature from promising coverage it cannot have.
# Forum software, and how to tell which one is answering.
#
# Signals are NOT equal, and the ranking was measured against the curated
# twelve rather than reasoned about:
#
# * **Cookies are the strongest.** They are set by the forum application even
#   when a bot defence answers on its behalf: `cracked.sh` came back as a
#   DDoS-Guard interstitial (`__ddg*` cookies) and still carried
#   `mybb[lastactive]` / `mybb[lastvisit]`. A cookie cannot be faked by the
#   challenge page's markup, which is exactly what body markers cannot promise.
# * **`generator` / `X-Powered-By` are next.** Explicit self-declaration, but
#   routinely stripped.
# * **Body markers are the weakest and the most dangerous.** `hackforums.net`
#   answered HTTP 403 with 200 KB of Cloudflare challenge markup, out of which
#   the first version of this function happily read "invision". Body markers
#   are therefore scored to zero whenever a challenge answered — see
#   `detect_software`.
#
# `url_profile` / `url_thread` are the shapes a search-engine hit takes on that
# software. They are what lets the hunt say "this handle HAS AN ACCOUNT here"
# instead of "this string appears somewhere on this host" — see
# `crime_forum_runner.classify_hit`.
_SOFTWARE: tuple[dict, ...] = (
    {"name": "xenforo",
     "cookies": ("xf_", "xf_csrf", "xf_session"),
     "declared": ("xenforo",),
     "body": ('data-app="xf"', "xenforo", "/js/xf/"),
     "member": "/members/", "profile": "",
     "url_profile": ("/members/",), "url_thread": ("/threads/", "/posts/")},
    {"name": "mybb",
     "cookies": ("mybb[", "mybbuser", "sid"),
     "declared": ("mybb",),
     "body": ("mybb", "member.php?action=profile", "inc/jscripts"),
     "member": "/memberlist.php",
     "profile": "/member.php?action=profile&username={u}",
     "url_profile": ("member.php?action=profile", "member.php?uid"),
     "url_thread": ("showthread.php", "thread-")},
    {"name": "phpbb",
     "cookies": ("phpbb3_", "phpbb_"),
     "declared": ("phpbb",),
     "body": ("phpbb", "styles/prosilver", "ucp.php"),
     "member": "/memberlist.php",
     "profile": "/memberlist.php?mode=viewprofile&un={u}",
     "url_profile": ("memberlist.php?mode=viewprofile",),
     "url_thread": ("viewtopic.php",)},
    {"name": "discourse",
     "cookies": ("_forum_session", "_t"),
     "declared": ("discourse",),
     "body": ("discourse", "discourse-application"),
     "member": "/u", "profile": "/u/{u}",
     "url_profile": ("/u/",), "url_thread": ("/t/",)},
    {"name": "flarum",
     "cookies": ("flarum_session", "flarum_remember"),
     "declared": ("flarum",),
     "body": ("flarum",),
     "member": "/u", "profile": "/u/{u}",
     "url_profile": ("/u/",), "url_thread": ("/d/",)},
    {"name": "smf",
     "cookies": ("smfcookie", "smf_"),
     "declared": ("smf", "simple machines"),
     "body": ("simple machines", "?action=mlist"),
     "member": "/index.php?action=mlist", "profile": "",
     "url_profile": ("action=profile",), "url_thread": ("topic=", "?msg=")},
    {"name": "vbulletin",
     "cookies": ("bbsessionhash", "bblastvisit"),
     "declared": ("vbulletin",),
     "body": ("vbulletin", "vbseo"),
     "member": "/memberlist.php", "profile": "",
     "url_profile": ("member.php?u=",), "url_thread": ("showthread.php",)},
    {"name": "invision",
     "cookies": ("ips4_", "ipsconnect"),
     "declared": ("invision", "invision community"),
     # Deliberately NOT "ips_"/"ipb": both are short enough to occur inside
     # unrelated markup, and this is the entry a challenge page mis-triggered.
     "body": ("invision community", "ipsclass", "data-ipsjs"),
     "member": "/profile/", "profile": "",
     "url_profile": ("/profile/",), "url_thread": ("/topic/",)},
)

# A forum root is tens of kilobytes. Measured: `xss.is` answers
# HTTP 200 with **380 bytes**, `exploit.in` with 3 KB, `ogusers.gg` with 3.4 KB
# — none of them a forum page, all of them an interstitial that carries none of
# the Cloudflare phrases. Judging software from such a body is judging the
# challenge, so size is a signal in its own right.
MIN_FORUM_BODY = int(os.getenv("FORUM_MIN_BODY", "6000") or 6000)

# Bot defence visible at the transport level rather than in the text. Survives
# translation and custom challenge pages, both of which the phrase list cannot.
_DEFENCE_COOKIES = ("__ddg", "__cf_bm", "cf_clearance", "sucuri_cloudproxy",
                    "incap_ses", "visid_incap")


def _score_software(low: str, cookie_names: tuple[str, ...],
                    declared: str, trust_body: bool) -> list[tuple[int, str, dict]]:
    """Score every candidate. Cookie 3, self-declaration 2, body marker 1."""
    scored: list[tuple[int, str, dict]] = []
    for sw in _SOFTWARE:
        score, why = 0, ""
        for c in sw["cookies"]:
            if any(c in n for n in cookie_names):
                score, why = score + 3, f"cookie {c}"
                break
        if any(d in declared for d in sw["declared"]):
            score, why = score + 2, why or "declared"
        if trust_body and any(m in low for m in sw["body"]):
            score, why = score + 1, why or "markup"
        if score:
            scored.append((score, why, sw))
    scored.sort(key=lambda t: -t[0])
    return scored

# The forum answered and said "not for guests". Matched on the body because
# these boards return the wall with HTTP 200 far more often than with 401/403.
_LOGIN_MARKERS = (
    "you must be logged in", "you must login", "please log in", "please login",
    "log in or sign up", "login or register", "you have to register",
    "must be registered", "registration is required", "members only",
    "guests are not allowed", "you do not have permission", "no permission to",
    "not authorised to", "not authorized to", "access denied",
    # German/Russian boards are a large part of this pool.
    "sie müssen angemeldet", "bitte anmelden", "nur für mitglieder",
    "registrierung erforderlich", "необходимо войти", "только для",
    "войдите", "регистрация",
)
# A login FORM on the member area is the same statement made in markup, and it
# survives translation — which the phrase list above cannot.
_LOGIN_FORM_RE = re.compile(
    r"<input[^>]+type=[\"']?password[\"']?", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def detect_software(body: str, cookie_names: tuple[str, ...] = (),
                    headers: dict | None = None,
                    challenged: bool = False) -> tuple[str, str, str, str]:
    """Return `(software, member_path, profile_template, why)`.

    `why` names the signal that decided it, so the panel can show *how* the
    answer was reached rather than asking the operator to trust a label.

    **Body markers are ignored when a challenge answered** (`challenged`), and
    when the body is too small to be a forum. Both were measured: reading
    software out of a Cloudflare page gave `hackforums.net` the wrong engine,
    and `xss.is` served 380 bytes with HTTP 200. A wrong software name is worse
    than none — it would hand the hunt the wrong profile and thread patterns
    and quietly mislabel every hit on that board.
    """
    low = (body or "").lower()
    hdr = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    declared = " ".join((hdr.get("x-powered-by", ""),
                         hdr.get("server", ""),
                         _GENERATOR_RE.search(body or "").group(1).lower()
                         if _GENERATOR_RE.search(body or "") else ""))
    trust_body = not challenged and len(body or "") >= MIN_FORUM_BODY
    scored = _score_software(low, tuple(n.lower() for n in cookie_names),
                             declared, trust_body)
    if not scored:
        return "", "", "", ""
    top, why, sw = scored[0]
    # A single weak body marker is a guess, not a detection — and a guess here
    # propagates into the search patterns. Require corroboration or a stronger
    # class of signal.
    if top < 2 and len(scored) > 1 and scored[1][0] == top:
        return "", "", "", ""
    return sw["name"], sw["member"], sw["profile"], why


def _detect_software(body: str) -> tuple[str, str, str]:
    """Body-only shim kept for the offline suite and any direct caller."""
    name, member, profile, _ = detect_software(body)
    return name, member, profile


HIT_PROFILE = "profile"
HIT_THREAD = "thread"


def classify_url(url: str, software: str = "") -> str:
    """Is this search hit a member PROFILE or a thread/post — or neither?

    The distinction the hunt was missing. `site:<forum> "<handle>"` returns a
    profile page and a post that merely quotes the handle as the same kind of
    row, with the same confidence, and an analyst reading "found on 6 forums"
    could not tell "has accounts on 6 boards" from "was named in 6 threads".
    Those are different statements about a person and only one of them makes
    them a member.

    Generic over every known software rather than keyed on the detected one:
    the pattern is in the URL the engine already returned, so this works for
    the boards whose software is unknown or hidden behind a challenge — which,
    measured on the curated twelve, is most of them. Passing `software`
    narrows it to that engine's patterns and removes the (rare) cross-engine
    ambiguity, e.g. `/u/` meaning a profile on Discourse and Flarum only.
    """
    u = (url or "").lower()
    table = [s for s in _SOFTWARE if not software or s["name"] == software]
    for key, verdict in (("url_profile", HIT_PROFILE), ("url_thread", HIT_THREAD)):
        for sw in table:
            if any(p in u for p in sw[key]):
                return verdict
    return ""


def defence_in_cookies(cookie_names: tuple[str, ...]) -> str:
    """Which bot defence set a cookie, if any. Independent of page language."""
    for n in cookie_names:
        for d in _DEFENCE_COOKIES:
            if d in n.lower():
                return d
    return ""


async def _probe_index(client: httpx.AsyncClient, domain: str,
                       key: str) -> dict:
    """How much of this forum the search engine has, via `site:<domain>`.

    No contact with the forum. This is the measurement that decides whether
    the forum can contribute to a hunt at all.
    """
    if is_onion(domain):
        return {"index_status": IDX_NOT_APPLICABLE, "index_count": 0,
                "index_note": "hidden service — not in any clearnet index"}
    if not key:
        return {"index_status": IDX_NO_KEY, "index_count": 0}
    try:
        r = await client.get(
            BRAVE_API,
            params={"q": f"site:{domain}", "count": str(INDEX_SAMPLE)},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        if r.status_code in (401, 403):
            return {"index_status": IDX_ERROR, "index_count": 0,
                    "index_note": f"search API rejected the key (HTTP {r.status_code})"}
        if r.status_code == 429:
            return {"index_status": IDX_ERROR, "index_count": 0,
                    "index_note": "search API rate limit"}
        if r.status_code != 200:
            return {"index_status": IDX_ERROR, "index_count": 0,
                    "index_note": f"search API HTTP {r.status_code}"}
        results = (r.json().get("web", {}) or {}).get("results", []) or []
        # Count only hits actually ON that host: `site:` is usually honoured,
        # but a fallback to a fuzzy match would otherwise credit a forum with
        # somebody else's pages.
        hits = [x for x in results if domain in str(x.get("url", ""))]
        return {
            "index_status": IDX_INDEXED if hits else IDX_NOT_INDEXED,
            "index_count": len(hits),
            "index_note": "",
        }
    except Exception as e:  # noqa: BLE001
        return {"index_status": IDX_ERROR, "index_count": 0,
                "index_note": f"{type(e).__name__}"}


async def _fingerprint_retry(url: str) -> dict | None:
    """Ask again with a real browser's TLS fingerprint. Returns None on no gain.

    Measured across a sample of 70 clearnet forums classed as `blocked`,
    both paths over the same Tor proxy: plain httpx got 27 usable
    answers, curl_cffi with `impersonate="chrome"` got 32. **Five boards
    answer only to the fingerprint** — two that returned a challenge page
    (`darkmarket.at`, `rutor.live`) and three that returned HTTP 429
    (`crax.pro`, `eleaks.to`, `ver.sc`).

    Deliberately a RETRY, not a replacement. The httpx path carries 54
    checked invariants and produces the right answer for 65 of the 70; a
    swap would put all of that at risk to gain five. This runs only after the
    normal path has already said "blocked", so a board that was reachable
    anyway is never touched twice.

    **What it changes is also a finding, not just a workaround.** A board
    that answers a browser fingerprint and refuses a library one screens on
    TLS rather than on address or rate — that is a property of the target
    worth recording, so the note says which path got in.

    ⚠️ This does NOT bypass a real challenge. Cloudflare's interstitial with
    JavaScript stays shut; 29 of the 70 remained blocked either way.
    """
    if not HAVE_CURL or not TOR_PROXY:
        return None
    try:
        async with _CurlSession(
            proxies={"http": TOR_PROXY, "https": TOR_PROXY},
            timeout=REACH_TIMEOUT, verify=False,
        ) as sess:
            r = await sess.get(url, impersonate="chrome", allow_redirects=True)
    except Exception:  # noqa: BLE001 — the normal path's verdict stands
        return None

    body = (r.text or "")[:200_000]
    low = body.lower()
    if any(m in low for m in _CHALLENGE_MARKERS):
        return None
    if r.status_code in (403, 429, 503) or not (200 <= r.status_code < 400):
        return None
    tm = _TITLE_RE.search(body)
    title = re.sub(r"\s+", " ", tm.group(1)).strip()[:120] if tm else ""
    return {"reach_status": REACH_ONLINE,
            "reach_note": f"HTTP {r.status_code} (browser TLS fingerprint; the "
                          "plain client was refused — this board screens on "
                          "fingerprint)",
            "title": title}


async def _probe_reach(domain: str) -> dict:
    """Is the host answering at all — asked over Tor, never from our address.

    **No local DNS pre-flight here, deliberately.** The obvious guard is
    `safe_fetch.assert_public_url`, and it was in this function until it was
    measured: it resolves the name with the *local* resolver, and three of
    the twelve default forums do not resolve locally at all
    (`breachforums.st` NXDOMAIN, `nulled.to` and `cracked.io` SERVFAIL).
    The request itself goes out over **socks5h**, where the name is resolved
    Tor-side — so the guard was refusing to check precisely the hosts that
    only Tor can reach, and reporting an operator-side DNS fact as an error
    about the forum.

    Dropping it costs nothing: with socks5h the hostname never touches our
    resolver and the connection is made by the Tor exit, which cannot reach
    anything on the operator's network. `safe_fetch` states the same rule in
    its own docstring — the Tor path is exempt from the private-address
    model. The syntactic guard still applies upstream: `normalize_domain`
    rejects bare IPs, ports and anything without a dotted TLD before a
    domain can ever be stored.
    """
    if not TOR_PROXY:
        return {"reach_status": REACH_NO_TOR, "reach_note": "", "title": ""}

    # Hidden services overwhelmingly speak plain HTTP: the onion address is
    # itself the authenticated endpoint, so most operators never obtain a
    # certificate. Asking for https:// first would report a live forum as
    # unreachable on a TLS handshake that was never going to succeed.
    url = f"http://{domain}/" if is_onion(domain) else f"https://{domain}/"
    try:
        async with httpx.AsyncClient(
            proxy=TOR_PROXY, timeout=REACH_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            verify=False,   # seized/parked forums routinely serve broken certs
        ) as client:
            r = await client.get(url)
    except Exception as e:  # noqa: BLE001
        # Deliberately NOT "offline": over Tor an exit-side failure and a dead
        # host produce the same exception.
        return {"reach_status": REACH_UNREACHABLE,
                "reach_note": f"{type(e).__name__}", "title": ""}

    body = (r.text or "")[:200_000]
    low = body.lower()
    tm = _TITLE_RE.search(body)
    title = re.sub(r"\s+", " ", tm.group(1)).strip()[:120] if tm else ""

    if any(m in low for m in _CHALLENGE_MARKERS):
        return (await _fingerprint_retry(url)
                or {"reach_status": REACH_BLOCKED, "reach_note": "bot defence",
                    "title": title})
    if r.status_code in (403, 429, 503):
        return (await _fingerprint_retry(url)
                or {"reach_status": REACH_BLOCKED,
                    "reach_note": f"HTTP {r.status_code}", "title": title})
    if 200 <= r.status_code < 400:
        return {"reach_status": REACH_ONLINE, "reach_note": f"HTTP {r.status_code}",
                "title": title}
    return {"reach_status": REACH_UNREACHABLE, "reach_note": f"HTTP {r.status_code}",
            "title": title}


async def _probe_access(domain: str) -> dict:
    """Can a GUEST read the member area — or does this forum demand an account?

    The third question, and the one that decides what is even buildable per
    forum. The `index` probe says what a search engine got out of a board from
    the outside; this says what *we* could get out of it directly, as nobody.

    Two steps, both over Tor:

    1. Fetch the root, fingerprint the forum software. That yields where the
       member area lives and — decisively — whether a profile can be addressed
       by NAME at all. XenForo, SMF and vBulletin key profiles on a numeric id,
       so no per-handle existence check can ever work there; MyBB, phpBB,
       Discourse and Flarum take the name.
    2. Fetch the member area and read the answer: a login wall, real content,
       or a bot defence.

    **`login_required` is a fact about this forum, never a to-do.** Turning it
    into "so give the framework an account" is a decision with a legal shape,
    not a configuration step — see docs/operations.en.md. This probe exists to make the
    question answerable, not to answer it.
    """
    if not TOR_PROXY:
        return {"access_status": ACC_NO_TOR, "access_note": "",
                "software": "", "profile_template": ""}

    scheme = "http" if is_onion(domain) else "https"
    async with httpx.AsyncClient(
        proxy=TOR_PROXY, timeout=REACH_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        verify=False,
    ) as client:
        try:
            root = await client.get(f"{scheme}://{domain}/")
        except Exception as e:  # noqa: BLE001
            return {"access_status": ACC_UNREACHABLE,
                    "access_note": f"{type(e).__name__}",
                    "software": "", "profile_template": ""}

        body = (root.text or "")[:200_000]
        cookies = tuple(root.cookies.keys())
        # Three independent readings of "a bot defence answered, not the forum":
        # a known phrase, a defence cookie, and a body far too small to be a
        # forum root. The last two exist because the first misses every one
        # of the custom interstitials seen in practice.
        phrase = any(m in body.lower() for m in _CHALLENGE_MARKERS)
        defence = defence_in_cookies(cookies)
        stub = len(body) < MIN_FORUM_BODY
        # ⚠️ A DEFENCE COOKIE ON ITS OWN IS NOT A REFUSAL.
        #
        # Cloudflare's `__cf_bm` and DDoS-Guard's `__ddg*` are set on EVERY
        # response they proxy, including the successful ones. Reading the
        # cookie as a verdict marks every WAF-fronted board as blocked
        # whether or not it answered.
        #
        # Measured on `cracked.sh`: HTTP 200, **415 040 bytes of MyBB
        # markup**, and MyBB's own session cookies (`mybb[lastvisit]`,
        # `sid`) sitting in the same response as `__ddg1_`. The forum
        # answered; a cookie-only verdict would record it as `blocked`.
        #
        # The same misreading explains why boards classed `blocked` can be
        # seen answering normally on a plain httpx A/B: such entries are not
        # stale, they are false.
        #
        # The cookie keeps doing the work it was added for:
        # naming WHICH defence, and tipping the balance when the body is a
        # stub or the status refuses. It just no longer decides alone.
        challenged = bool(phrase)

        software, member_path, profile, why = detect_software(
            body, cookies, dict(root.headers),
            challenged=challenged or stub or root.status_code in (401, 403, 429, 503))

        # A refusing status on the ROOT is a bot defence too, even when the
        # body carries no phrase and is large enough to look like a page.
        # Measured: hackforums.net answers the root with HTTP 403
        # and 200 KB of challenge markup — reading that as "the forum answered,
        # we just don't recognise it" understates it, and reading software out
        # of it is what produced a false `invision` before.
        refused = root.status_code in (401, 403, 429, 503)
        if challenged or stub or refused:
            if phrase:
                note = f"bot defence ({defence})" if defence else "bot defence"
            elif refused:
                note = f"HTTP {root.status_code} on the root"
            else:
                note = f"interstitial, {len(body)} B — not a forum page"
            if defence and not phrase:
                note += f" ({defence})"
            # A cookie survives the challenge, so the software may still be
            # known. Report it; just never claim the member area was seen.
            return {"access_status": ACC_BLOCKED, "access_note": note[:60],
                    "software": software if why.startswith("cookie") else "",
                    "profile_template": profile if why.startswith("cookie") else ""}

        # Past this point the board answered with a real page. If a WAF is in
        # front of it, that is worth recording — it explains why a later
        # probe may be refused from a different circuit — but it is a
        # property of the target, not a result.
        waf_note = f"; behind {defence}" if defence else ""

        if not member_path:
            # The root answered with a real page, but nothing identifies the
            # software — so we do not know where the member area is and must
            # not claim it is open.
            return {"access_status": ACC_UNKNOWN,
                    "access_note": ("forum software not recognised" + waf_note)[:60],
                    "software": software, "profile_template": ""}

        try:
            page = await client.get(f"{scheme}://{domain}{member_path}")
        except Exception as e:  # noqa: BLE001
            return {"access_status": ACC_UNREACHABLE,
                    "access_note": f"member area: {type(e).__name__}",
                    "software": software, "profile_template": profile}

    text = (page.text or "")[:200_000]
    low = text.lower()
    result = {"software": software, "profile_template": profile}

    if any(m in low for m in _CHALLENGE_MARKERS):
        return {**result, "access_status": ACC_BLOCKED, "access_note": "bot defence"}
    if page.status_code in (401, 403):
        return {**result, "access_status": ACC_LOGIN,
                "access_note": f"HTTP {page.status_code}"}
    if page.status_code == 404:
        # The ROOT answered — the board is up and its software was recognised.
        # Only the member area is not where that software normally puts it,
        # which boards routinely arrange (renamed, disabled, or behind a
        # different route). Measured on `cracked.sh` and
        # `sinister.ly`, both MyBB, both 404 on `/memberlist.php`. Calling that
        # `unreachable` would state "this forum is down" on the strength of a
        # page that was never the forum.
        return {**result, "access_status": ACC_UNKNOWN,
                "access_note": f"no member area at {member_path}"}
    if page.status_code >= 400:
        return {**result, "access_status": ACC_UNREACHABLE,
                "access_note": f"HTTP {page.status_code}"}

    hit = next((m for m in _LOGIN_MARKERS if m in low), "")
    if hit:
        return {**result, "access_status": ACC_LOGIN, "access_note": hit[:60]}
    # A password field on the member area means the board answered with its
    # login form. Checked after the phrase list so the note can name the phrase
    # when there was one, and it catches the boards no phrase list covers.
    if _LOGIN_FORM_RE.search(text) and "logout" not in low:
        return {**result, "access_status": ACC_LOGIN, "access_note": "login form"}
    # The final URL still being the member area (rather than /login) plus a body
    # of a plausible size is as close to "readable" as a guest probe gets.
    if len(text) < 500:
        return {**result, "access_status": ACC_UNKNOWN,
                "access_note": f"empty response ({len(text)} bytes)"}
    return {**result, "access_status": ACC_OPEN,
            "access_note": f"HTTP {page.status_code}"}


async def check_forums(domains: list[str], mode: str = "index",
                       options: dict | None = None) -> dict[str, dict]:
    """Probe each domain and return `{domain: result}`.

    `mode`:
      * ``index``  — search-engine coverage only. No contact with the forum.
      * ``reach``  — Tor reachability only.
      * ``access`` — can a guest read the member area, and which software is
        it. Contacts the forum, over Tor, like ``reach``.
      * ``both``   — index + reach (unchanged meaning: `access` is slower and
        makes two requests per host, so it is never implied).

    Results carry `checked_at` so the console can distinguish "never checked"
    from "checked and fine" — the two look identical without it, and that
    difference decides whether an operator trusts the column.
    """
    wanted = [d for d in dict.fromkeys(domains) if d]
    if not wanted:
        return {}
    do_index = mode in ("index", "both")
    do_reach = mode in ("reach", "both")
    do_access = mode == "access"
    key = credential(options, "BRAVE_API_KEY") if do_index else ""
    stamp = _now()
    sem = asyncio.Semaphore(max(1, CHECK_CONCURRENCY))
    out: dict[str, dict] = {}

    async def one(domain: str, client: "httpx.AsyncClient | None") -> None:
        async with sem:
            res: dict = {"checked_at": stamp}
            if do_index and client is not None:
                res.update(await _probe_index(client, domain, key))
            if do_reach:
                res.update(await _probe_reach(domain))
            if do_access:
                res.update(await _probe_access(domain))
            out[domain] = res

    if do_index:
        async with httpx.AsyncClient(timeout=25) as client:
            await asyncio.gather(*[one(d, client) for d in wanted])
    else:
        await asyncio.gather(*[one(d, None) for d in wanted])
    return out
