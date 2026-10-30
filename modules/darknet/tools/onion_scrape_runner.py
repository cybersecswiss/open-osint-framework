"""
Onion content analysis — pull selectors out of a hidden service's pages.

This is the pivot step after a darknet search: a search tells you a service
EXISTS, this tells you who it is connected to. It fetches a hidden service
over Tor and extracts the identifiers an investigator can pivot on — contact
addresses, crypto wallets, messenger IDs, PGP keys and links to other onion
services — turning a single onion node into a connected sub-graph.

Deliberate limits, because this is the first tool in the stack that fetches
darknet CONTENT rather than reading a search index:

* **Blacklisted hosts are never fetched.** Ahmia's abuse blacklist is
  enforced as a hard precondition here and, unlike the display filter in
  ahmia_runner, it is NOT switchable. If the list cannot be loaded, nothing
  is fetched (fail closed), and linked services on the list are withheld. Showing a search hit is one thing;
  having framework infrastructure download the material is another, and
  that belongs in a controlled forensic process with its own legal basis,
  not in an OSINT search tool. A blocked target is reported, not hidden.
* **Text only.** Responses are accepted only for text/html and text/plain,
  and the body is capped (``ONION_SCRAPE_MAX_BYTES``). No images, no
  archives, no downloads — nothing that could persist media on the
  investigator's machine or the server.
* **Shallow.** The entry page plus at most ``ONION_SCRAPE_MAX_PAGES-1``
  contact-ish subpages on the SAME host. This is not a crawler, and it
  never follows a link to a different service.

Everything runs through the bundled Tor SOCKS proxy; without
``TOR_SOCKS_PROXY`` the tool reports that it cannot run rather than
attempting a clearnet fetch.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from schemas import NOTE_PREFIX, EdgeResult, Finding

from .ahmia_runner import AhmiaBlacklist, ONION_RE, USER_AGENT

TOR_PROXY = os.getenv("TOR_SOCKS_PROXY", "").strip()
MAX_PAGES = max(1, int(os.getenv("ONION_SCRAPE_MAX_PAGES", "3") or 3))
# Safety net against a link-directory dumping thousands of nodes into a case.
# A link list legitimately yields ~80, so the cap sits well above that and,
# as everywhere in this stack, the note reports what was left out.
MAX_SELECTORS = int(os.getenv("ONION_SCRAPE_MAX_SELECTORS", "150") or 150)
MAX_BYTES = int(os.getenv("ONION_SCRAPE_MAX_BYTES", "2000000") or 2000000)
PAGE_TIMEOUT = int(os.getenv("ONION_SCRAPE_TIMEOUT", "60") or 60)

ALLOWED_CONTENT = ("text/html", "text/plain", "application/xhtml")

# Subpages worth a second look — where onion services put contact details.
CONTACT_HINTS = ("contact", "about", "impressum", "support", "help",
                 "pgp", "key", "faq", "info", "abuse", "rules")

# --- selector patterns -------------------------------------------------
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Bitcoin: legacy (1/3) + bech32. Bounded to avoid matching prose.
BTC_RE = re.compile(r"\b(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-z0-9]{20,60})\b")
ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
# PGP fingerprints: 40 hex chars, optionally spaced in groups of 4.
PGP_RE = re.compile(r"\b(?:[A-F0-9]{4}\s?){10}\b", re.I)
TOX_RE = re.compile(r"\b[A-F0-9]{76}\b", re.I)
SESSION_RE = re.compile(r"\b05[a-f0-9]{64}\b", re.I)
JABBER_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.onion\b")
TELEGRAM_RE = re.compile(r"(?:t\.me/|telegram(?:\s*[:@]\s*|\s+))@?([A-Za-z0-9_]{5,32})\b", re.I)

# Files/assets whose names would otherwise trip the BTC pattern.
_NOISE = re.compile(r"\.(png|jpg|jpeg|gif|css|js|woff2?|svg|ico)$", re.I)

log = logging.getLogger("module-darknet.onion_scrape")


def _normalize_target(query: str) -> str | None:
    """Accept a bare host, a full URL, or something with surrounding text."""
    m = ONION_RE.search((query or "").strip().lower())
    return m.group(0) if m else None


def _all_onions(text: str) -> set[str]:
    """Every .onion host in *text*, WITH the suffix.

    ONION_RE has a capture group for the base32 part, so ``findall`` would
    return hosts *without* ``.onion`` — which silently produced a second
    node for every service already known under its full name. Always match
    on group(0).
    """
    return {m.group(0).lower() for m in ONION_RE.finditer(text or "")}


def _ok_content_type(resp: httpx.Response) -> bool:
    ctype = (resp.headers.get("content-type") or "").lower()
    return any(a in ctype for a in ALLOWED_CONTENT) or not ctype


async def _fetch(client: httpx.AsyncClient,
                 url: str) -> tuple[str | None, str | None]:
    """Fetch one page as text.

    Returns ``(text, reason_it_failed)`` — the reason is surfaced to the
    analyst instead of a generic "unreachable", because "expired
    certificate" and "service is down" call for very different next steps.
    """
    try:
        async with client.stream("GET", url, timeout=PAGE_TIMEOUT) as resp:
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            if not _ok_content_type(resp):
                ctype = (resp.headers.get("content-type") or "?").split(";")[0]
                return None, f"not text ({ctype}) — skipped by policy"
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    log.info("onion_scrape: %s exceeded %d bytes, truncated",
                             url, MAX_BYTES)
                    break
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace"), None
    except Exception as e:  # noqa: BLE001
        log.warning("onion_scrape: %s failed: %s", url, e)
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def _pick_subpages(html: str, host: str, limit: int) -> list[str]:
    """Contact-ish links on the same host, most promising first."""
    soup = BeautifulSoup(html, "html.parser")
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "javascript:", "#")):
            continue
        full = href if href.startswith("http") else urllib.parse.urljoin(
            f"http://{host}/", href)
        p = urllib.parse.urlparse(full)
        if host not in p.netloc.lower() or full in seen:
            continue
        blob = f"{p.path} {a.get_text(' ', strip=True)}".lower()
        score = sum(1 for h in CONTACT_HINTS if h in blob)
        if score:
            seen.add(full)
            scored.append((score, full))
    scored.sort(key=lambda t: -t[0])
    return [u for _, u in scored[:limit]]


def _extract(text: str, host: str) -> dict[str, set[str]]:
    """Pull selectors out of page text. Returns {kind: {values}}."""
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    visible = soup.get_text(" ", strip=True)
    # mailto: links carry addresses that the visible text may not repeat.
    mailtos = {
        a["href"][7:].split("?")[0].strip()
        for a in soup.find_all("a", href=True)
        if a["href"].lower().startswith("mailto:")
    }
    haystack = f"{visible} {' '.join(mailtos)}"

    jabber = {j.lower() for j in JABBER_RE.findall(haystack)}
    emails = {e.lower() for e in set(EMAIL_RE.findall(haystack)) | mailtos
              if e and not _NOISE.search(e)}
    # An address at an .onion domain is a messenger ID, not a mailbox.
    emails -= jabber

    out = {
        "email": emails,
        "jabber_id": jabber,
        "btc_address": {b for b in BTC_RE.findall(haystack) if not _NOISE.search(b)},
        "eth_address": {e.lower() for e in ETH_RE.findall(haystack)},
        "tox_id": {t.upper() for t in TOX_RE.findall(haystack)},
        "session_id": {s.lower() for s in SESSION_RE.findall(haystack)},
        "pgp_key": {re.sub(r"\s+", "", p).upper() for p in PGP_RE.findall(text)},
        "telegram_user": {t.lower() for t in TELEGRAM_RE.findall(haystack)},
        # Links to OTHER hidden services — the darknet link graph.
        "onion_service": {h for h in _all_onions(text) if h != host},
    }
    # A Tox ID is 76 hex chars and a PGP fingerprint 40 — no overlap, but a
    # session id (05 + 64 hex = 66) can look like neither. Keep them apart.
    out["pgp_key"] -= {p for p in out["pgp_key"] if len(p) != 40}
    return {k: v for k, v in out.items() if v}


# Relation label per selector kind, and how much to trust it.
_REL = {
    "email":          ("contact_email", 0.75),
    "jabber_id":      ("contact_jabber", 0.8),
    "btc_address":    ("payment_address", 0.8),
    "eth_address":    ("payment_address", 0.8),
    "tox_id":         ("contact_tox", 0.8),
    "session_id":     ("contact_session", 0.8),
    "pgp_key":        ("pgp_key_of", 0.8),
    "telegram_user":  ("contact_telegram", 0.6),
    "onion_service":  ("links_to", 0.7),
}


async def run_onion_scrape(query: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    host = _normalize_target(query)
    if not host:
        return [], [], [f"onion_scrape: '{query}' is not a .onion address"]

    if not TOR_PROXY:
        return [], [], ["onion_scrape: no TOR_SOCKS_PROXY configured — a hidden "
                        "service cannot be reached without Tor."]

    # --- hard abuse gate, before a single byte is requested -------------
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as c:
        blacklist_ok = await AhmiaBlacklist.load(c)
    if blacklist_ok and AhmiaBlacklist.is_banned(host):
        return [], [], [
            f"onion_scrape: {host} is on Ahmia's abuse blacklist — refused. "
            "Content of blacklisted services is deliberately never fetched by "
            "this framework; handle such material through the forensic "
            "process, not an OSINT tool."
        ]
    if not blacklist_ok:
        # Fail CLOSED: without the list the target cannot be checked, and an
        # unchecked fetch is exactly what this gate exists to prevent.
        return [], [], [
            "onion_scrape: Ahmia's abuse blacklist could not be loaded — "
            "refusing to fetch an unchecked hidden service. Try again later."
        ]

    # --- fetch -----------------------------------------------------------
    pages: dict[str, str] = {}
    entry = f"http://{host}/"
    async with httpx.AsyncClient(
        proxy=TOR_PROXY, follow_redirects=True,
        # TLS verification off ON PURPOSE, and only for .onion: hidden
        # services routinely serve expired or self-signed certificates, and
        # the onion address itself is already the cryptographic identity —
        # Tor authenticates the endpoint, so a failed chain check adds no
        # security here while silently costing us most targets. This client
        # is used exclusively for onion fetches through the Tor proxy.
        verify=False,
        headers={"User-Agent": USER_AGENT,
                 "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        body, reason = await _fetch(client, entry)
        if body is None:
            return [], [], [f"onion_scrape: {host} could not be read — {reason}. "
                            "The service may be offline, or it is not a website."]
        pages[entry] = body

        if MAX_PAGES > 1:
            subs = _pick_subpages(body, host, MAX_PAGES - 1)
            if subs:
                fetched = await asyncio.gather(
                    *(_fetch(client, u) for u in subs))
                for url, (text, _why) in zip(subs, fetched):
                    if text:
                        pages[url] = text

    # --- extract ---------------------------------------------------------
    merged: dict[str, set[str]] = {}
    for text in pages.values():
        for kind, values in _extract(text, host).items():
            merged.setdefault(kind, set()).update(values)

    title = ""
    soup = BeautifulSoup(pages[entry], "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()[:200]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    # The service itself, so the extracted selectors have something to hang
    # off even when this tool runs standalone. Same identity as the node
    # ahmia_runner produces (entity_type + bare host as label), so a scrape
    # ENRICHES the existing node instead of creating a second one.
    findings.append(Finding(
        entity_type="onion_service",
        platform="tor",
        label=host,
        url=entry,
        confidence=0.9,          # we fetched it — stronger than a search hit
        data={"onion": host, "title": title, "url": entry,
              "pages_read": len(pages), "source": "onion_scrape",
              "selectors_found": {k: len(v) for k, v in merged.items()}},
    ))

    # Linked services go through the same gate: a blacklisted service must
    # not enter the case as a node just because another page links to it.
    linked = merged.get("onion_service")
    if linked:
        banned = {h for h in linked if AhmiaBlacklist.is_banned(h)}
        if banned:
            merged["onion_service"] = linked - banned
            if not merged["onion_service"]:
                del merged["onion_service"]
            notes.append(NOTE_PREFIX + f"{len(banned)} linked service(s) on the "
                                       "abuse blacklist withheld.")

    total_selectors = sum(len(v) for v in merged.values())
    if total_selectors > MAX_SELECTORS:
        # Trim the biggest bucket first (usually the onion link list) so a
        # directory page can't crowd out the rarer, more valuable selectors
        # like a PGP key or a wallet address.
        budget = MAX_SELECTORS
        trimmed: dict[str, set[str]] = {}
        for kind, values in sorted(merged.items(), key=lambda kv: len(kv[1])):
            share = max(1, budget // max(1, len(merged) - len(trimmed)))
            keep = sorted(values)[:share] if len(values) > share else sorted(values)
            trimmed[kind] = set(keep)
            budget -= len(keep)
        merged = trimmed
        notes.append(NOTE_PREFIX + f"{total_selectors} selectors found, "
                                   f"{sum(len(v) for v in merged.values())} "
                                   "kept (ONION_SCRAPE_MAX_SELECTORS).")

    for kind, values in merged.items():
        relation, conf = _REL[kind]
        for value in sorted(values):
            findings.append(Finding(
                entity_type=kind,
                platform="tor",
                label=value,
                url=f"http://{value}" if kind == "onion_service" else None,
                confidence=conf,
                data={"found_on": host, "source": "onion_scrape",
                      "context": title},
            ))
            # Endpoint MUST equal the finding key "{entity_type}:{label}".
            edges.append(EdgeResult(
                from_entity=f"onion_service:{host}",
                to_entity=f"{kind}:{value}",
                relation=relation,
                confidence=conf,
            ))

    if len(pages) > 1:
        notes.append(NOTE_PREFIX + f"Read {len(pages)} pages on {host} "
                                   "(entry page + contact pages).")
    if not merged:
        notes.append(NOTE_PREFIX + f"{host} was readable but contained no "
                                   "extractable selectors (no addresses, "
                                   "wallets or messenger IDs).")
    return findings, edges, errors + notes
