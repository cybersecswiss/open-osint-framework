"""Handle sweep — the same actor under their other spellings.

Every other username tool in this framework asks about the one string the
analyst typed. Cybercrime actors do not use one string: `d4rkc1ph3r` on one
forum is `darkcipher` on the next, `dark_cipher` on a third, `darkcipher1`
after a ban. Reuse is what betrays them, and exact matching is what makes the
framework miss it.

This tool runs the WhatsMyName sweep over the typed handle **and** its
plausible variants, then reports which spelling produced each account.

Why a separate tool rather than a flag on `whatsmyname`
-------------------------------------------------------
It costs what it costs: one sweep is ~600 HTTP probes and ~55 seconds, and
this runs several. Making it a flag would either slow every username search
or hide the cost behind a default nobody reads. As its own entry in the tool
picker, choosing it *is* the informed opt-in, and the analyst who selects it
knows why they are waiting.

What a hit means
----------------
An account found under a *variant* is a candidate, not an identification.
`darkcipher` on Reddit and `d4rkc1ph3r` on XSS may be two people who both like
the word. Findings carry `match_type`, name the spelling that produced them,
and rate lower than a direct hit — corroboration (shared password, PGP key,
forum, wallet, writing style) is what closes that gap, not this tool.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from handle_variants import transliterate, variants
from schemas import EdgeResult, Finding, NOTE_PREFIX
from tools.whatsmyname_runner import (CONCURRENCY, USER_AGENT, _fetch_sites,
                                      _probe)
from verifier import verify_findings

log = logging.getLogger("module-alias.handle_sweep")

# Each extra spelling is a full ~600-site sweep. Three keeps the worst case
# near three minutes; more turns a search into something an analyst abandons
# halfway, which is worse than not offering it.
MAX_SPELLINGS = 3


def _spellings(username: str) -> list[str]:
    """The typed handle first, then its most plausible variants."""
    out = [username]
    for cand in variants(username, MAX_SPELLINGS * 2):
        if cand.casefold() not in {o.casefold() for o in out}:
            out.append(cand)
        if len(out) >= MAX_SPELLINGS + 1:
            break
    latin = transliterate(username)
    if latin and latin.casefold() not in {o.casefold() for o in out}:
        out.append(latin)
    return out[:MAX_SPELLINGS + 1]


async def run_handle_sweep(
    username: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    handle = (username or "").strip().lstrip("@")
    if not handle:
        return [], [], ["handle_sweep: empty username"]

    spellings = _spellings(handle)
    if len(spellings) == 1:
        return [], [], [
            f"{NOTE_PREFIX}handle_sweep: '{handle}' has no plausible spelling "
            "variants (too short, or already the plainest form) — a normal "
            "whatsmyname search covers it."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    per_spelling: dict[str, int] = {}

    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT},
                                     timeout=httpx.Timeout(15)) as client:
            try:
                sites = await _fetch_sites(client)
            except Exception as e:  # noqa: BLE001
                return [], [], [f"handle_sweep: failed to fetch site list: {e}"]

            sem = asyncio.Semaphore(CONCURRENCY)
            for spelling in spellings:
                is_exact = spelling.casefold() == handle.casefold()
                results = await asyncio.gather(
                    *[_probe(client, sem, s, spelling) for s in sites],
                    return_exceptions=True)
                hits = [r for r in results if isinstance(r, Finding)]

                # Same false-positive problem as whatsmyname, same remedy —
                # and it matters more here, because a false positive on a
                # guessed spelling is a false lead built on a false lead.
                raw = len(hits)
                hits = await verify_findings(hits, spelling)
                if raw - len(hits) > 0:
                    errors.append(
                        f"{NOTE_PREFIX}handle_sweep: {raw - len(hits)} false "
                        f"positives filtered for '{spelling}' "
                        f"({len(hits)}/{raw} verified)")

                per_spelling[spelling] = len(hits)
                for f in hits:
                    f.confidence = 0.8 if is_exact else 0.4
                    f.data = {**(f.data or {}),
                              "match_type": "exact" if is_exact else "variant",
                              "spelling": spelling,
                              "searched_username": handle,
                              "source": "handle_sweep"}
                    if not is_exact:
                        f.data["note"] = (
                            f"Found under the variant spelling '{spelling}', "
                            f"not under the searched '{handle}'. A candidate — "
                            "confirm the accounts belong to the same person "
                            "before relying on it.")
                    findings.append(f)
                    edges.append(EdgeResult(
                        from_entity=f"username:{handle}",
                        to_entity=f"social_account:{f.label}",
                        relation="is_account_of" if is_exact
                        else "possible_account_of",
                        confidence=0.8 if is_exact else 0.4,
                    ))
    except Exception as e:  # noqa: BLE001
        return findings, edges, errors + [f"handle_sweep error: {e}"]

    swept = ", ".join(f"{s} ({n})" for s, n in per_spelling.items())
    errors.append(f"{NOTE_PREFIX}handle_sweep: swept {len(spellings)} spellings "
                  f"— {swept}. Accounts under a variant spelling are candidates "
                  "and rated lower; they are NOT confirmed to be the same person.")
    return findings, edges, errors
