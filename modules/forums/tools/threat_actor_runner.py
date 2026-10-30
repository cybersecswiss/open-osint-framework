"""
Threat-actor username check (keyless, cached index).

Answers "is this username a KNOWN cybercrime-forum actor, and on which
forums?" by looking it up in a baked index of ~830k usernames scraped from
25 crime forums (spmedia/Threat-Actor-Usernames-Scrape: BreachForums,
Cracked, HackForums, XSS, OGUsers, Dread, RAMP …).

Pure local lookup — zero live calls, instant. A hit is a strong LE signal:
the handle is used on cybercrime forums. Emits a `threat_actor` node linked
to the searched username so it stands out in the graph, carrying the list of
forums (and which are now seized/dead) in its data.

Index: gzipped `{username_lower: [forum, …]}`. Refreshed copy in the /cache
volume (via POST /threat-actors/refresh) wins over the image-baked seed.

**Spelling variants.** An exact lookup would let `d4rkm4st3r` miss the
`darkmaster` the index holds — and handle mutation is the norm in
this population, not the exception. The variants are now tried too, but as
*candidates*: a variant hit carries a lower confidence, is labelled with the
handle that was actually found, and says so in `match_type`.

The obvious implementation — canonicalising all 830k entries into a second
index — was measured and rejected: the index alone occupies ~345 MB and
building a second one OOM-killed the container. Generating the handful of
variants for the *query* instead and looking each up costs no memory at all
and a dozen hash lookups.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
from pathlib import Path

from handle_variants import transliterate, variants
from schemas import EdgeResult, Finding, NOTE_PREFIX

log = logging.getLogger("module-forums.threat_actor")

# Enough to cover the usual mutations without turning one lookup into a
# fishing expedition; every extra candidate is another chance at a false lead.
MAX_CANDIDATES = 12


def _candidates(username: str) -> list[str]:
    """Spellings to try besides the one the analyst typed.

    A Cyrillic handle also gets its Latin transliteration (and that form's
    own variants) — Russian-language forums are the main stage here and the
    same actor is written both ways.
    """
    out = variants(username, MAX_CANDIDATES)
    latin = transliterate(username)
    if latin and latin.casefold() != username.casefold():
        for cand in [latin, *variants(latin, 4)]:
            if cand not in out:
                out.append(cand)
    return out[:MAX_CANDIDATES]

_CACHE = Path(os.getenv("THREAT_ACTORS_CACHE", "/cache/threat_actors.json.gz"))
_BAKED = Path(__file__).resolve().parent.parent / "data" / "threat_actors.json.gz"

_loaded: dict | None = None
_loaded_key: tuple | None = None


def _index_path() -> Path | None:
    if _CACHE.is_file():
        return _CACHE
    if _BAKED.is_file():
        return _BAKED
    return None


def _load() -> dict:
    """Lazy-load + memoise the index (kept out of startup so the container
    stays light until the tool is actually used). Reloads if the file changed."""
    global _loaded, _loaded_key
    path = _index_path()
    if path is None:
        return {}
    key = (str(path), path.stat().st_mtime)
    if _loaded is not None and _loaded_key == key:
        return _loaded
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            _loaded = json.load(f)
        _loaded_key = key
    except Exception as e:  # noqa: BLE001
        log.warning("failed to load threat-actor index %s: %s", path, e)
        return {}
    return _loaded


async def run_threat_actor_check(
    query: str, query_type: str = "username", job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    username = (query or "").strip().lstrip("@")
    if not username:
        return [], [], ["threat_actor_check: empty username"]

    data = _load()
    index = data.get("index") if isinstance(data, dict) else None
    if not index:
        return [], [], [
            "Threat-actor index not available. Build it with the module's "
            "POST /threat-actors/refresh, or rebuild the module image (a seed "
            "is baked in)."
        ]

    total = data.get("username_count")
    dead = set(data.get("dead_forums") or [])
    root = f"username:{username.lower()}"

    # (handle as the index spells it, forums, exact?) — the exact hit first so
    # it wins the dedup below if a variant happens to resolve to it as well.
    hits: list[tuple[str, list, bool]] = []
    exact = index.get(username.lower())
    if exact:
        hits.append((username, exact, True))

    tried: list[str] = []
    for cand in _candidates(username):
        tried.append(cand)
        forums = index.get(cand.lower())
        if forums and not any(h[0].lower() == cand.lower() for h in hits):
            hits.append((cand, forums, False))

    if not hits:
        note = (f"{NOTE_PREFIX}'{username}' is NOT in the known cybercrime-forum "
                f"actor index ({total} usernames / {data.get('forum_count')} "
                f"forums)")
        note += (f"; {len(tried)} spelling variants were tried too."
                 if tried else ".")
        return [], [], [note]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    for handle, forums, is_exact in hits:
        active = [f for f in forums if f not in dead]
        seized = [f for f in forums if f in dead]
        findings.append(Finding(
            entity_type="threat_actor", platform="crime-forums",
            label=handle, url=None,
            # A variant is a lead, not an identification: same handle shape,
            # unproven same person. Corroboration has to carry it the rest of
            # the way, so it must not arrive looking like a direct hit.
            confidence=0.7 if is_exact else 0.4,
            data={"username": handle, "forums": sorted(forums),
                  "active_forums": sorted(active), "seized_forums": sorted(seized),
                  "forum_count": len(forums),
                  "match_type": "exact" if is_exact else "variant",
                  "searched_username": username,
                  "note": ("Known cybercrime-forum handle (spmedia index)."
                           if is_exact else
                           f"Spelling variant of the searched '{username}' — "
                           "a candidate, NOT an identification. Confirm via a "
                           "second signal (shared password, PGP key, forum, "
                           "wallet) before treating it as the same actor."),
                  "source": "spmedia/Threat-Actor-Usernames-Scrape"},
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"threat_actor:{handle}",
            relation="known_crime_actor" if is_exact else "possible_handle_variant",
            confidence=0.7 if is_exact else 0.4,
        ))

    variant_hits = [h for h, _, ex in hits if not ex]
    if variant_hits:
        errors.append(
            f"{NOTE_PREFIX}threat_actor_check: {len(variant_hits)} hit(s) came "
            f"from a spelling variant of '{username}' ({', '.join(variant_hits)}), "
            "not from the handle as searched. Candidates — corroborate before use.")
    return findings, edges, errors
