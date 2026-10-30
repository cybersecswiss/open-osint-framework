"""RansomLook — leak-site posts, ransom notes, markets, actor aliases, wallets.

Complements `ransomware_watch` (ransomware.live) rather than duplicating it.
Both track leak sites; what RansomLook adds, measured against the live API,
is:

  * **ransom notes** — the note text itself, keyed to the group that uses it.
    An investigator holding a note file off a seized machine can ask "who
    writes this?", which is a question nothing else in this framework answers.
  * **markets and forums** — a name index of ~200 underground markets and
    boards, so a market name in a report resolves to something.
  * **wallets per group**, with balance and transaction counts, sourced from
    ransomwhe.re.
  * **actor aliases** — small but high-value, see the honest note below.

Two tools, deliberately not three:

    ransomlook_search  keyword → groups, markets, victim posts, ransom notes
    ransomlook_crypto  keyword → the wallets attributed to that group

### What was measured, and what it means for expectations

The actor index holds **30 actors with 14 aliases in total** (e.g. LockBitSupp
→ putincrab, NeroWolfe, PutinKrab, Pin). That is far smaller than the API
documentation implies, and far too small to be its own tool: a tool that
answers "no" for 99.99 % of handles trains an analyst to ignore it. It is
folded into `ransomlook_search` as an enrichment instead, where a hit is a
bonus rather than the promise. When it grows, splitting it out is one
descriptor.

**No reverse wallet lookup.** `/api/crypto/links` is empty and there is no
address→group endpoint, so "who owns this wallet" cannot be answered here —
`wallet_attribution` in the crypto module remains the tool for that. Iterating
every group to build a reverse index was rejected: ~200 requests per search
against a free service is abuse, not engineering.

### Licence

Code AGPL-3.0 — not used, and deliberately not read while writing this. The
**data** is CC BY 4.0, which permits commercial reuse with attribution, so
every finding carries `source: "ransomlook.io"` and the attribution travels
into the case file and out through the exporters.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

BASE = "https://www.ransomlook.io/api"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 35
ATTRIB = "RansomLook (ransomlook.io), CC BY 4.0"

# Caps. A broad term like "lock" matches dozens of groups; the head is the
# useful part and the note says how much was left out.
MAX_GROUPS = 15
MAX_POSTS = 40
MAX_NOTES = 10
MAX_MARKETS = 20
MAX_WALLETS = 60

# A ransom note is evidence, not prose — but the full text of one belongs in
# the analyst's own file, not as a graph node label. Store a bounded excerpt.
NOTE_EXCERPT = 1200

log = logging.getLogger("module-threat.ransomlook")

# The actor index is 30 entries; fetching it per search would be wasteful and
# fetching it once per process is plenty for something that changes monthly.
_ACTOR_TTL = 6 * 3600
_actors: list[dict[str, Any]] = []
_actors_at: float = 0.0


async def _get(client: httpx.AsyncClient, path: str) -> Any | None:
    try:
        r = await client.get(f"{BASE}{path}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.info("ransomlook %s failed: %s", path, e)
        return None


async def _actor_index(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    global _actors, _actors_at
    if _actors and (time.time() - _actors_at) < _ACTOR_TTL:
        return _actors
    data = await _get(client, "/actors/")
    if isinstance(data, list):
        _actors = data
        _actors_at = time.time()
    return _actors


def _match_actor(actors: list[dict[str, Any]], term: str) -> dict[str, Any] | None:
    """Resolve a handle against the actor index, by name OR by alias.

    Matching an alias is the point: an investigator who has "Fisheye" learns
    that it is bassterlord, which is the direction the lookup is actually
    useful in.
    """
    t = term.strip().lower()
    for a in actors:
        if (a.get("name") or "").lower() == t:
            return a
        if any((al or "").lower() == t for al in a.get("aliases") or []):
            return a
    return None


def _clean(s: Any, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


async def run_ransomlook_search(
    query: str, query_type: str = "keyword", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if len(term) < 2:
        return [], [], ["RansomLook: query must be at least 2 characters"]

    root = f"keyword:{term}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    notes: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        data = await _get(client, f"/search?q={quote(term)}")
        if data is None:
            return [], [], ["RansomLook: search endpoint unreachable"]
        if isinstance(data, dict) and data.get("message"):
            return [], [], [f"RansomLook: {data['message']}"]

        actors = await _actor_index(client)

    if not isinstance(data, dict):
        return [], [], ["RansomLook: unexpected response shape"]

    # --- groups -----------------------------------------------------------
    groups = data.get("groups") or []
    for g in groups[:MAX_GROUPS]:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        findings.append(Finding(
            entity_type="ransomware_group",
            platform="ransomlook",
            label=name,
            url=f"https://www.ransomlook.io/group/{quote(name)}",
            confidence=0.8,
            data={
                "meta": _clean(g.get("meta"), 2000),
                "source": "ransomlook.io",
                "attribution": ATTRIB,
            },
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"ransomware_group:{name}",
            relation="matches_group", data={"source": "ransomlook"},
        ))
    if len(groups) > MAX_GROUPS:
        notes.append(NOTE_PREFIX + f"{len(groups) - MAX_GROUPS} further group "
                                   f"matches not shown (showing {MAX_GROUPS}).")

    # --- victim posts -----------------------------------------------------
    posts = data.get("posts") or []
    for p in posts[:MAX_POSTS]:
        title = _clean(p.get("post_title"), 200)
        grp = (p.get("group_name") or "").strip()
        if not title:
            continue
        findings.append(Finding(
            entity_type="ransomware_victim",
            platform="ransomlook",
            label=title,
            url=p.get("link") or None,
            confidence=0.7,
            data={
                "group": grp,
                "discovered": p.get("discovered"),
                "description": _clean(p.get("description"), 800),
                # The screenshot and the MISP UUID are what make a leak-site
                # claim citable later; both are cheap to carry and expensive
                # to reconstruct.
                "screenshot": p.get("screen"),
                "misp_uuid": p.get("misp_uuid"),
                "source": "ransomlook.io",
                "attribution": ATTRIB,
            },
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"ransomware_victim:{title}",
            relation="mentioned_in_leak", data={"source": "ransomlook"},
        ))
        if grp:
            edges.append(EdgeResult(
                from_entity=f"ransomware_group:{grp}",
                to_entity=f"ransomware_victim:{title}",
                relation="claimed_by", data={"source": "ransomlook"},
            ))
    if len(posts) > MAX_POSTS:
        notes.append(NOTE_PREFIX + f"{len(posts) - MAX_POSTS} further leak-site "
                                   f"posts not shown (showing {MAX_POSTS}).")

    # --- ransom notes -----------------------------------------------------
    # The reason this tool exists: match a note found on a seized machine to
    # the group that writes it.
    for n in (data.get("notes") or [])[:MAX_NOTES]:
        fname = _clean(n.get("name"), 160) or "ransom note"
        grp = (n.get("group_name") or "").strip()
        label = f"{grp}: {fname}" if grp else fname
        findings.append(Finding(
            entity_type="ransom_note",
            platform="ransomlook",
            label=label,
            url=(f"https://www.ransomlook.io/notes/{quote(grp)}" if grp else None),
            confidence=0.75,
            data={
                "group": grp,
                "filename": fname,
                "excerpt": _clean(n.get("content"), NOTE_EXCERPT),
                "source": "ransomlook.io",
                "attribution": ATTRIB,
            },
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"ransom_note:{label}",
            relation="matches_note", data={"source": "ransomlook"},
        ))
        if grp:
            edges.append(EdgeResult(
                from_entity=f"ransom_note:{label}",
                to_entity=f"ransomware_group:{grp}",
                relation="used_by", data={"source": "ransomlook"},
            ))

    # --- markets ----------------------------------------------------------
    for m in (data.get("markets") or [])[:MAX_MARKETS]:
        name = (m.get("name") if isinstance(m, dict) else str(m or "")).strip()
        if not name:
            continue
        findings.append(Finding(
            entity_type="darknet_market",
            platform="ransomlook",
            label=name,
            url=f"https://www.ransomlook.io/market/{quote(name)}",
            confidence=0.6,
            data={"source": "ransomlook.io", "attribution": ATTRIB},
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"darknet_market:{name}",
            relation="matches_market", data={"source": "ransomlook"},
        ))

    # --- actor aliases (enrichment, see the module docstring) -------------
    hit = _match_actor(actors, term)
    if hit:
        name = hit.get("name") or term
        aliases = [a for a in (hit.get("aliases") or []) if a]
        findings.append(Finding(
            entity_type="threat_actor",
            platform="ransomlook",
            label=name,
            url=f"https://www.ransomlook.io/actor/{quote(name)}",
            confidence=0.8,
            data={
                "aliases": aliases,
                "wanted": bool(hit.get("has_wanted")),
                "source": "ransomlook.io",
                "attribution": ATTRIB,
            },
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"threat_actor:{name}",
            relation="known_actor", data={"source": "ransomlook"},
        ))
        # Each alias becomes its own username node joined to the actor. That
        # is the whole value: two handles an investigator was tracking
        # separately end up on one node.
        for al in aliases:
            edges.append(EdgeResult(
                from_entity=f"threat_actor:{name}",
                to_entity=f"username:{al.lower()}",
                relation="alias_of", data={"source": "ransomlook"},
            ))
            findings.append(Finding(
                entity_type="username", platform="ransomlook", label=al,
                confidence=0.7,
                data={"actor": name, "source": "ransomlook.io",
                      "attribution": ATTRIB},
            ))

    if not findings:
        notes.append(NOTE_PREFIX + "RansomLook knows nothing about this term "
                                   "(groups, markets, leak posts and ransom "
                                   "notes were all checked).")
    return findings, edges, errors + notes


async def run_ransomlook_crypto(
    query: str, query_type: str = "keyword", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    """Wallets attributed to a ransomware group.

    Forward direction only — see the module docstring on why there is no
    address→group lookup here.
    """
    group = (query or "").strip().lower()
    if not group:
        return [], [], ["RansomLook: empty group name"]

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        data = await _get(client, f"/crypto/{quote(group)}")

    if not isinstance(data, dict) or not data.get("by_chain"):
        return [], [], [NOTE_PREFIX + f"RansomLook lists no wallets for "
                                      f"'{group}'. The group name must match "
                                      f"its listing (try ransomlook_search "
                                      f"first)."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    notes: list[str] = []
    grp_label = data.get("group") or group
    shown = 0

    for chain, wallets in (data.get("by_chain") or {}).items():
        # Only chains the framework can actually pivot on get a typed node;
        # anything else would be a node no tool can follow.
        etype = {"bitcoin": "btc_address", "ethereum": "eth_address"}.get(
            str(chain).lower())
        for w in wallets or []:
            addr = (w.get("address") or "").strip()
            if not addr:
                continue
            if shown >= MAX_WALLETS:
                break
            shown += 1
            findings.append(Finding(
                entity_type=etype or "crypto_address",
                platform="ransomlook",
                label=addr,
                url=None,
                confidence=0.75,
                data={
                    "chain": chain,
                    "group": grp_label,
                    # Balances are point-in-time and RansomLook says when it
                    # last refreshed them; carrying the timestamp keeps the
                    # figure interpretable instead of merely impressive.
                    "balance": w.get("balance"),
                    "balance_usd": w.get("balanceUSD"),
                    "tx_count": w.get("tx_count"),
                    "last_tx_time": w.get("last_tx_time"),
                    "updated_at": w.get("updated_at"),
                    "upstream_source": w.get("source"),
                    "source": "ransomlook.io",
                    "attribution": ATTRIB,
                },
            ))
            edges.append(EdgeResult(
                from_entity=f"ransomware_group:{grp_label}",
                to_entity=f"{etype or 'crypto_address'}:{addr}",
                relation="controls_wallet", data={"source": "ransomlook"},
            ))

    total = data.get("total")
    if isinstance(total, int) and total > shown:
        notes.append(NOTE_PREFIX + f"{total - shown} further wallets not shown "
                                   f"(showing {shown} of {total}).")
    for al in data.get("aliases") or []:
        edges.append(EdgeResult(
            from_entity=f"ransomware_group:{grp_label}",
            to_entity=f"ransomware_group:{al}",
            relation="alias_of", data={"source": "ransomlook"},
        ))
    return findings, edges, notes
