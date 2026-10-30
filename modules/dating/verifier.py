"""
Shared account-existence verifier for OSINT modules.

Canonical copy: modules/base/verifier.py. Each consuming module's
Dockerfile copies this file into its build context (`COPY verifier.py .`,
imported as `from verifier import verify_findings`) so modules don't
share a Python package via volume mount — same convention as schemas.py.
Keep the per-module copies byte-identical with the base copy. Any module
that discovers social/web accounts by URL (username/alias pivoting,
future e-mail/handle modules) can reuse it unchanged.

Post-process social-account findings: drop false positives so the graph
only shows accounts that actually exist.

A finding survives only if BOTH gates pass:

  Gate 1 — direct probe of the profile URL:
    1. HTTP 200 on a redirect-following GET.
    2. The queried username still appears in the FINAL URL (platforms
       redirect missing accounts to /, /login, /404 … where the
       username disappears).
    3. Body contains none of the known "not found" phrases.

  Gate 2 — negative control (the strong FP killer):
    Re-request the SAME url template with a random, near-certainly
    non-existent username and compare. The candidate must be
    *distinguishable* from that control:
      - control 4xx/5xx while candidate 200  → platform properly 404s
        unknown users → candidate is real.
      - control redirected away (its username vanished from the final
        URL) while the candidate kept its username → real.
      - both 200 & templated: bodies differ in length beyond a
        threshold, OR the username appears in the candidate body but the
        control string does not appear in the control body → real.
    If the candidate is INDISTINGUISHABLE from a nonexistent user
    (classic catch-all page that 200s for anything), it is dropped.
    If the control request itself fails, we fall back to Gate 1 only
    (no regression vs. the previous behaviour).

Both gates run concurrently across all findings (capped at CONCURRENCY),
each request times out individually, and the whole pass has a hard
ceiling so one slow host can't stall the module.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets

import httpx

from schemas import NOTE_PREFIX, Finding

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CONCURRENCY = 20
PER_REQ_TIMEOUT = 10
# Hard ceiling on the whole verification pass — even with per-request
# timeouts, a large hit list against slow hosts could otherwise stall
# the module well past the orchestrator's patience.
TOTAL_TIMEOUT = 110
# Relative body-length difference above which two 200-pages are treated
# as genuinely different content (candidate vs. negative control).
LEN_DIFF_RATIO = 0.15
# Phrases sites use to indicate "no such user" while still serving 200.
# Lowercased. Ordered roughly by frequency.
NOT_FOUND_PHRASES = (
    "page not found", "user not found", "account not found",
    "doesn't exist", "does not exist", "no such user",
    "not registered", "no user found", "user does not exist",
    "this account doesn", "couldn't find this account",
    "sorry, that page", "404 - not found", "page introuvable",
    "nicht gefunden", "non trovato", "no se encontró",
    "diese seite gibt es nicht",
)

log = logging.getLogger("module-alias.verifier")


def _make_control_username(username: str) -> str:
    """A random, near-certainly unregistered username of similar shape."""
    token = secrets.token_hex(5)  # 10 hex chars
    # keep it plausibly valid (letters first) but improbable
    return f"zq{token}"


async def _fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 url: str) -> tuple[int, str, str] | None:
    """Return (status, final_url, body) or None on network error."""
    async with sem:
        try:
            r = await client.get(url, timeout=PER_REQ_TIMEOUT,
                                 follow_redirects=True)
        except (httpx.TimeoutException, httpx.RequestError):
            return None
    return r.status_code, str(r.url), r.text


async def _verify_one(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                      f: Finding, username: str, control: str) -> Finding | None:
    if not f.url:
        return None
    user_low = username.lower()
    control_low = control.lower()

    # ---- Gate 1: direct probe ----
    cand = await _fetch(client, sem, f.url)
    if cand is None:
        return None
    status, final_url, body = cand
    if status != 200:
        return None
    final_low = final_url.lower()
    body_low = body.lower()
    if user_low not in final_low:
        return None
    if any(phrase in body_low for phrase in NOT_FOUND_PHRASES):
        return None

    # ---- Gate 2: negative control ----
    method = "heuristic"
    confidence = 0.85
    if user_low in f.url.lower():
        control_url = re.sub(re.escape(username), control, f.url, flags=re.IGNORECASE)
        ctrl = await _fetch(client, sem, control_url)
        if ctrl is not None:
            c_status, c_final, c_body = ctrl
            distinguished = False
            if c_status != 200:
                # site returns an error for unknown users → candidate real
                distinguished = True
            else:
                c_final_low = c_final.lower()
                if control_low not in c_final_low:
                    # control got bounced away but candidate kept its name
                    distinguished = True
                else:
                    lc, lb = len(c_body), len(body)
                    if max(lc, lb) > 0 and abs(lc - lb) / max(lc, lb) > LEN_DIFF_RATIO:
                        distinguished = True
                    if user_low in body_low and control_low not in c_body.lower():
                        distinguished = True
            if not distinguished:
                # indistinguishable from a nonexistent user → catch-all page
                return None
            method = "negative-control"
            confidence = 0.95

    new_data = dict(f.data or {})
    new_data["verified"] = True
    new_data["verify_method"] = method
    new_data["final_url"] = final_url
    return f.copy(update={
        "confidence": min(0.98, max(f.confidence or 0.7, confidence)),
        "data": new_data,
    })


async def verify_accounts(
    findings: list["Finding"],
    edges: list,
    username: str,
    tool: str,
) -> tuple[list["Finding"], list, str | None]:
    """Verify the account findings in a mixed result set, then repair the edges.

    Runners that emit more than one KIND of finding (accounts *and* e-mail
    addresses, say) cannot hand the whole list to `verify_findings`: it drops
    everything without a URL, so the non-account findings would vanish. And
    every runner that filters findings has to filter its edges too, or the
    dropped endpoints come back as virtual placeholder nodes in the graph —
    the false positive survives as a hollow node instead of disappearing.

    Both mistakes are easy to make once per runner, so the logic lives here.

    Returns ``(findings, edges, note)``. The note is prefixed for
    ``make_run_response`` so filtering false positives is reported as
    information and does NOT mark the run as partial — a working filter is
    not a failure.
    """
    verifiable = [f for f in findings if f.entity_type == "social_account" and f.url]
    passthrough = [f for f in findings if f not in verifiable]
    if not verifiable:
        return findings, edges, None

    kept = await verify_findings(verifiable, username)
    dropped = len(verifiable) - len(kept)
    findings = kept + passthrough

    if dropped:
        # Keep only edges whose endpoints still exist. Endpoint keys follow the
        # module convention `entity_type:label`, which is what build_graph
        # resolves against.
        surviving = {f"{f.entity_type}:{f.label}" for f in findings}
        edges = [
            e for e in edges
            if (not e.to_entity.startswith("social_account:") or e.to_entity in surviving)
            and (not e.from_entity.startswith("social_account:") or e.from_entity in surviving)
        ]

    note = None
    if dropped:
        note = (f"{NOTE_PREFIX}{tool}: {dropped} false positive(s) filtered "
                f"({len(kept)}/{len(verifiable)} accounts verified)")
    return findings, edges, note


async def verify_findings(findings: list[Finding], username: str) -> list[Finding]:
    """Return only findings whose URL passed verification.
    Falls back to the original list on a top-level error."""
    if not findings:
        return findings
    control = _make_control_username(username)
    headers = {"User-Agent": USER_AGENT,
               "Accept": "text/html,application/xhtml+xml"}
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = httpx.Timeout(PER_REQ_TIMEOUT, connect=PER_REQ_TIMEOUT)
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout,
                                     follow_redirects=True) as client:
            checked = await asyncio.wait_for(
                asyncio.gather(
                    *[_verify_one(client, sem, f, username, control) for f in findings],
                    return_exceptions=True,
                ),
                timeout=TOTAL_TIMEOUT,
            )
    except asyncio.TimeoutError:
        log.warning("verifier exceeded %ss; returning unverified findings", TOTAL_TIMEOUT)
        return findings
    except Exception:  # noqa: BLE001
        log.exception("verifier crashed; returning unverified findings")
        return findings
    out: list[Finding] = []
    for r in checked:
        if isinstance(r, Finding):
            out.append(r)
    return out
