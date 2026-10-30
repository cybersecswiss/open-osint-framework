"""
LinkBase directory lookup (keyless, cached index).

Answers "which hacking / carding / crime boards match this keyword or name,
and how do I reach them (onion / Telegram) ?" from link-base.ms — the long-
running "world's biggest linklist for security & hacking boards" (~290 boards,
categorised by language).

Why a cached index and not a live call: link-base.ms rate-limits its JSON API
hard (~1 req / 2s; a throttled call returns the string "Rate Limit Exceeded"
with HTTP 200), so crawling ~290 boards per search is impossible. Instead a
seed index is crawled slowly and baked into the image
(`data/linkbase_index.json`); the operator can refresh it into the `/cache`
volume via the module's `POST /linkbase/refresh` (runs `linkbase_crawl.py`).
This runner only reads that file — zero live API calls at search time.

Emits the board itself (`crime_forum`) plus well-canonicalised pivot nodes
(`onion_service` for its TOR address, `telegram_channel` for its Telegram),
so results dedup with the darknet / messenger / telegram modules.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from schemas import EdgeResult, Finding, NOTE_PREFIX

log = logging.getLogger("module-forums.linkbase")

# Refreshed index (written by /linkbase/refresh into the volume) wins over the
# seed baked into the image at build time.
_CACHE_INDEX = Path(os.getenv("LINKBASE_CACHE", "/cache/linkbase_index.json"))
_BAKED_INDEX = Path(__file__).resolve().parent.parent / "data" / "linkbase_index.json"

MAX_RESULTS = 40
DETAIL_URL = "https://link-base.ms/redirect/Board/{id}"

# In-process cache keyed on (path, mtime) so a refreshed file is picked up
# without a container restart.
_loaded: dict | None = None
_loaded_key: tuple | None = None

_ONION_RE = re.compile(r"([a-z2-7]{16}|[a-z2-7]{56})\.onion", re.I)


def _index_path() -> Path | None:
    if _CACHE_INDEX.is_file():
        return _CACHE_INDEX
    if _BAKED_INDEX.is_file():
        return _BAKED_INDEX
    return None


def _load_index() -> list[dict]:
    """Load and memoise the board index, refreshing if the file changed."""
    global _loaded, _loaded_key
    path = _index_path()
    if path is None:
        return []
    key = (str(path), path.stat().st_mtime)
    if _loaded is not None and _loaded_key == key:
        return _loaded.get("records", [])
    try:
        with path.open(encoding="utf-8") as f:
            _loaded = json.load(f)
        _loaded_key = key
    except Exception as e:  # noqa: BLE001
        log.warning("failed to load linkbase index %s: %s", path, e)
        return []
    return _loaded.get("records", [])


def _norm_onion(value: str) -> str | None:
    m = _ONION_RE.search(value or "")
    return m.group(0).lower() if m else None


def _norm_tg(value: str) -> str | None:
    """Normalise a Telegram field to a canonical @handle (matches the
    messenger/telegram modules so nodes dedup)."""
    v = (value or "").strip()
    if not v:
        return None
    v = re.sub(r"^https?://", "", v, flags=re.I)
    v = re.sub(r"^(t\.me|telegram\.me|telegram\.dog)/", "", v, flags=re.I)
    v = v.lstrip("@/").split("/")[0].split("?")[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", v):
        return None
    return "@" + v.lower()


def _matches(rec: dict, needle: str) -> tuple[bool, int]:
    """Return (is_match, rank). Lower rank = better (name hit beats info hit)."""
    name = (rec.get("Name") or "").lower()
    cat = (rec.get("Category") or "").lower()
    info = (rec.get("Information") or "").lower()
    if needle in name:
        return True, 0
    if needle == cat:
        return True, 1
    if needle in info:
        return True, 2
    return False, 9


async def run_linkbase_lookup(
    query: str, query_type: str = "keyword", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    needle = (query or "").strip().lower()
    if not needle:
        return [], [], ["LinkBase lookup: empty keyword"]

    records = _load_index()
    if not records:
        return [], [], [
            "LinkBase index not available. Build it once with the module's "
            "POST /linkbase/refresh (crawls link-base.ms slowly into the "
            "/cache volume), or rebuild the module image (a seed index is "
            "baked in at build time)."
        ]

    root = f"{query_type}:{needle}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    matched = []
    for rec in records:
        ok, rank = _matches(rec, needle)
        if ok:
            matched.append((rank, rec))
    # Best matches first; note if we had to cap.
    matched.sort(key=lambda x: (x[0], (x[1].get("Name") or "").lower()))
    total = len(matched)
    if total > MAX_RESULTS:
        errors.append(f"{NOTE_PREFIX}LinkBase: {total} boards matched "
                      f"'{needle}', showing the top {MAX_RESULTS}. Use a more "
                      "specific keyword to narrow it down.")
        matched = matched[:MAX_RESULTS]

    for _rank, rec in matched:
        name = (rec.get("Name") or "").strip()
        if not name:
            continue
        bid = rec.get("id")
        url = DETAIL_URL.format(id=bid) if bid is not None else None
        onion = _norm_onion(rec.get("TOR", ""))
        tg = _norm_tg(rec.get("Telegram", ""))
        non_fraud = str(rec.get("NonFraud", "")).lower() == "true"

        findings.append(Finding(
            entity_type="crime_forum", platform="link-base",
            label=name, url=url, confidence=0.6,
            data={
                "name": name,
                "language": rec.get("Category") or "",
                "non_fraud": non_fraud,
                "info": (rec.get("Information") or "")[:500],
                "onion": onion or "",
                "telegram": rec.get("Telegram") or "",
                "discord": rec.get("Discord") or "",
                "twitter": rec.get("Twitter") or "",
                "screenshot": rec.get("Screenshot") or "",
                "changed": rec.get("Changed") or "",
                "linkbase_id": bid,
                "url": url,
                "source": "link-base.ms",
            },
        ))
        edges.append(EdgeResult(from_entity=root,
                                to_entity=f"crime_forum:{name}",
                                relation="directory_match", confidence=0.6))

        if onion:
            findings.append(Finding(
                entity_type="onion_service", platform="tor",
                label=onion, url=f"http://{onion}", confidence=0.5,
                data={"onion": onion, "forum": name, "surface": "darknet",
                      "url": f"http://{onion}", "source": "link-base.ms"},
            ))
            edges.append(EdgeResult(from_entity=f"crime_forum:{name}",
                                    to_entity=f"onion_service:{onion}",
                                    relation="has_onion", confidence=0.5))

        if tg:
            findings.append(Finding(
                entity_type="telegram_channel", platform="telegram",
                label=tg, url=f"https://t.me/{tg.lstrip('@')}", confidence=0.5,
                data={"handle": tg, "forum": name,
                      "url": f"https://t.me/{tg.lstrip('@')}",
                      "source": "link-base.ms"},
            ))
            edges.append(EdgeResult(from_entity=f"crime_forum:{name}",
                                    to_entity=f"telegram_channel:{tg}",
                                    relation="linked_telegram", confidence=0.5))

    if not findings and not errors:
        errors.append(f"No LinkBase boards matched '{needle}'")
    return findings, edges, errors
