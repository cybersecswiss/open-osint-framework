"""
Ahmia's abuse blacklist — shared screening for EVERY onion result path.

## Why this is shared code and not a helper inside one module

This originally lived inside `modules/darknet/tools/ahmia_runner.py`.
It was applied by the two darknet tools and by nothing else, because nothing
else could reach it. `modules/forums`' Tor sweep queries the same engines
(Torch, TorDex) over the same proxy and had no way to import it, so a
keyword hunt could attach a blacklisted hidden service to the investigated
selector as an `onion_service` node — in the case graph, in the findings
list and in the PDF report.

That is the worst possible failure mode for an investigative tool, and
it was not a coding mistake: it was a *placement* mistake. Whoever adds the
next Tor-facing tool would have made it again.

So the fix is not "copy the class". It is `screen_hosts()`: one call that
loads the list, drops what is banned and returns the note explaining what
was withheld. A new onion path adds one `await` and inherits the policy,
the wording and the fail-open behaviour.

## The policy itself

* The list is a flat file of MD5 hex digests of onion hostnames INCLUDING
  the `.onion` suffix, lowercased (tens of thousands of entries).
* **Fail-open**, deliberately: if the list cannot be fetched we return
  results unfiltered and say so. Failing closed would hand back an empty
  result set that looks exactly like "nothing found", and an analyst would
  draw a conclusion from a network error.
* **Never drop silently.** Every removal produces a note. An analyst must be
  able to see that results were withheld and why — a filtered result set
  that does not admit it is worse than an unfiltered one. Notes use
  `NOTE_PREFIX`, so filtering never marks a run as partial: a working filter
  is not a failure.

`DARKNET_FILTER_ABUSE=false` disables it globally. The variable keeps its
original name because it is already documented and set in deployments; it
governs every onion path, not just the darknet module.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import TypeVar

import httpx

from schemas import NOTE_PREFIX

log = logging.getLogger("osint.onion_blacklist")

# On by default: it keeps abuse material out of the case graph, and an
# operator who needs the unfiltered set can turn it off knowingly.
FILTER_ABUSE = os.getenv("DARKNET_FILTER_ABUSE", "true").strip().lower() \
    not in ("false", "0", "no")


class AhmiaBlacklist:
    """Ahmia's MD5-hashed blacklist of abusive hidden services.

    Cached per process for an hour. See the module docstring for the policy;
    prefer `screen_hosts()` over calling this directly.
    """

    URL = "https://ahmia.fi/blacklist/banned/"
    TTL = 3600

    _hashes: set[str] = set()
    _fetched_at: float = 0.0

    @classmethod
    async def load(cls, client: httpx.AsyncClient) -> bool:
        if cls._hashes and (time.time() - cls._fetched_at) < cls.TTL:
            return True
        try:
            r = await client.get(cls.URL, timeout=20)
            r.raise_for_status()
            cls._hashes = {
                ln.strip() for ln in r.text.splitlines() if len(ln.strip()) == 32
            }
            cls._fetched_at = time.time()
            log.info("ahmia blacklist loaded: %d hashes", len(cls._hashes))
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("ahmia blacklist unavailable: %s", e)
            # A stale list still protects; only a never-loaded one does not.
            return bool(cls._hashes)

    @classmethod
    def is_banned(cls, host: str) -> bool:
        if not cls._hashes:
            return False
        return hashlib.md5(host.encode()).hexdigest() in cls._hashes


_M = TypeVar("_M", bound=dict)


async def screen_hosts(
    client: httpx.AsyncClient,
    hosts: _M,
    *,
    enabled: bool | None = None,
) -> tuple[_M, list[str]]:
    """Drop blacklisted onion hosts from a `{host: anything}` mapping.

    Returns `(kept, notes)`. The mapping's values are untouched, so this
    works for both `{host: title}` and `{host: {...}}` shapes.

    `client` should already be configured however the caller needs; the
    blacklist itself lives on the CLEARNET (ahmia.fi) and does not need the
    Tor proxy, but fetching it through Tor is harmless and one client is
    simpler than two.
    """
    if enabled is None:
        enabled = FILTER_ABUSE
    if not enabled or not hosts:
        return hosts, []

    notes: list[str] = []
    if not await AhmiaBlacklist.load(client):
        notes.append(NOTE_PREFIX + "Abuse blacklist could not be fetched — "
                                   "onion results are UNFILTERED.")
        return hosts, notes

    total = len(hosts)
    kept = {h: v for h, v in hosts.items() if not AhmiaBlacklist.is_banned(h)}
    removed = total - len(kept)
    if removed:
        notes.append(NOTE_PREFIX + f"{removed} of {total} onion results "
                                   "withheld — listed on Ahmia's abuse "
                                   "blacklist. Set DARKNET_FILTER_ABUSE=false "
                                   "to include them.")
    return kept, notes  # type: ignore[return-value]
