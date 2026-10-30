"""cupidcr4wl — username sweep across ADULT & DATING platforms.

Isolated in its own module (not the general alias sweep) so an
investigator opts into an adult/dating probe DELIBERATELY, case by case
(sextortion, romance-scam, trafficking, CSAM-adjacent leads) — it never
piggybacks on an ordinary username search.

Honest by construction, no fabricated hits:
  * Site list = the community-tested WhatsMyName data, FILTERED to the
    ``dating`` and ``xx NSFW xx`` categories (~50 platforms) — each entry
    ships a tested existence rule (expected status + ``e_string``).
  * Every candidate then passes the SHARED two-gate verifier
    (``verify_findings``): direct probe + negative-control against a random
    username, so catch-all pages that 200 for anyone are dropped.
  * A curated supplement adds a few high-signal adult/dating sites the
    upstream list misses, with the same rule shape.

Findings are ``dating_profile`` nodes (kept distinct from ordinary
``social_account`` so the sensitivity is visible in the graph) linked to
the queried username. Nothing auto-chains onto a person.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX
from verifier import verify_findings

log = logging.getLogger("module-dating.cupidcrawl")

LIST_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CONCURRENCY = 25
PER_SITE_TIMEOUT = 8
# WhatsMyName categories that are adult- or dating-oriented.
ADULT_DATING_CATS = {"dating", "xx NSFW xx"}

# Curated supplement — high-signal adult/dating sites, same rule shape as
# wmn (name, uri_check with {account}, e_code, e_string). Kept small and
# only sites with an unauthenticated profile page + a reliable positive
# marker; the verifier still re-checks each so a stale rule can't fabricate.
SUPPLEMENT = [
    {"name": "Fetlife", "cat": "xx NSFW xx",
     "uri_check": "https://fetlife.com/users/{account}", "e_code": 200,
     "e_string": "FetLife"},
    {"name": "Chaturbate", "cat": "xx NSFW xx",
     "uri_check": "https://chaturbate.com/{account}/", "e_code": 200,
     "e_string": "chaturbate"},
    {"name": "Pornhub", "cat": "xx NSFW xx",
     "uri_check": "https://www.pornhub.com/users/{account}", "e_code": 200,
     "e_string": "{account}"},
    {"name": "OnlyFans", "cat": "xx NSFW xx",
     "uri_check": "https://onlyfans.com/{account}", "e_code": 200,
     "e_string": "onlyfans"},
]


async def _fetch_sites(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(LIST_URL, timeout=15)
        r.raise_for_status()
        wmn = [s for s in ((r.json() or {}).get("sites") or [])
               if (s.get("cat") or "") in ADULT_DATING_CATS]
    except Exception as e:  # noqa: BLE001 — fall back to the supplement alone
        log.warning("wmn list fetch failed: %s", e)
        wmn = []
    # Merge, de-duped by lowercased name (wmn wins over supplement).
    seen = {(s.get("name") or "").lower() for s in wmn}
    merged = list(wmn) + [s for s in SUPPLEMENT if s["name"].lower() not in seen]
    return merged


async def _probe(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 site: dict, username: str) -> Finding | None:
    name = site.get("name") or "?"
    cat = site.get("cat") or ""
    e_code = int(site.get("e_code") or 200)
    e_string = (site.get("e_string") or "").replace("{account}", username)
    uri_check = (site.get("uri_check") or "").replace("{account}", username)
    if not uri_check:
        return None
    async with sem:
        try:
            r = await client.get(uri_check, timeout=PER_SITE_TIMEOUT,
                                 follow_redirects=True)
        except (httpx.TimeoutException, httpx.RequestError):
            return None
    if r.status_code != e_code:
        return None
    if e_string and e_string not in r.text:
        return None
    return Finding(
        entity_type="dating_profile",
        platform=name.lower(),
        label=f"{name.lower()}/{username}",
        url=uri_check,
        confidence=0.8,
        data={"username": username, "platform": name, "category": cat,
              "adult": True, "url": uri_check, "source": "cupidcrawl"},
    )


async def run_cupidcrawl(
    username: str, job_id: str = "adhoc"
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    username = (username or "").strip()
    if not username:
        return [], [], ["cupidcrawl: provide a username."]

    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(15),
                                     follow_redirects=True) as client:
            sites = await _fetch_sites(client)
            sem = asyncio.Semaphore(CONCURRENCY)
            results = await asyncio.gather(
                *[_probe(client, sem, s, username) for s in sites],
                return_exceptions=True,
            )
    except Exception as e:  # noqa: BLE001
        return [], [], [f"cupidcrawl error: {type(e).__name__}: {e}"]

    findings = [r for r in results if isinstance(r, Finding)]

    # Two-gate verifier kills catch-all / soft-404 false positives.
    raw = len(findings)
    findings = await verify_findings(findings, username)
    errors: list[str] = []
    dropped = raw - len(findings)
    if dropped > 0:
        errors.append(f"{NOTE_PREFIX}cupidcrawl: {dropped} false positives filtered "
                      f"({len(findings)}/{raw} verified across {len(sites)} adult/dating sites).")

    edges = [EdgeResult(
        from_entity=f"username:{username}",
        to_entity=f"dating_profile:{f.label}",
        relation="is_account_of", confidence=0.85,
    ) for f in findings]

    if not findings and dropped == 0:
        errors.append(f"{NOTE_PREFIX}No adult/dating profile found for '{username}' "
                      f"across {len(sites)} platforms.")
    return findings, edges, errors
