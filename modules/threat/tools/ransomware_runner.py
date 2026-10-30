"""Ransomware leak-site victims and groups — ransomware.live.

In a cybercrime investigation this is often the entry point to a case: an
organisation appears on a leak site, and the questions that follow are which
group claimed it, when, what else that group has posted, and where their
onion infrastructure is.

Two access tiers, both free:

  * **v2, keyless** — rate limited to *one request per minute per endpoint*.
    That is genuinely tight for an orchestrator that fires every tool of a
    module at once, so a 429 here is reported as a note with the remedy
    rather than as a failure.
  * **PRO, free with a key** from https://my.ransomware.live — no rate limit,
    500k calls/month. Set `RANSOMWARE_LIVE_API_KEY` in the Global-Admin
    settings and this runner uses it automatically.

Query types:
    domain / keyword → victim search (company name or domain)
    keyword          → also matched against group names, so searching a
                       group ("lockbit") returns the group profile
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding, credential

V2 = "https://api.ransomware.live/v2"
PRO = "https://api-pro.ransomware.live"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
MAX_VICTIMS = 60

log = logging.getLogger("module-threat.ransomware")


def _as_dt(value):
    """Leak-site date string -> datetime, None when unparseable. None is the
    honest answer; an invented date on an evidentiary field is worse."""
    from datetime import datetime
    if not value:
        return None
    for fmt in (None, "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return (datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if fmt is None else datetime.strptime(str(value), fmt))
        except ValueError:
            continue
    return None


def _base_and_headers(options: dict | None) -> tuple[str, dict[str, str], bool]:
    """Returns (base_url, headers, is_pro).

    The two tiers are NOT the same API behind one hostname — they expose
    different route names (see `_victim_search_url`). Callers therefore have
    to know which one they are talking to.
    """
    key = credential(options, "RANSOMWARE_LIVE_API_KEY")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if key:
        headers["X-API-KEY"] = key
        return PRO, headers, True
    return V2, headers, False


def _victim_search_url(base: str, selector: str, is_pro: bool) -> str:
    """Victim search differs by tier and getting this wrong is silent.

    v2   GET /searchvictims/<keyword>      (path segment)
    PRO  GET /victims/search?q=<keyword>   (query parameter)

    Using the v2 path against BOTH hosts is the trap: on the PRO host that
    is a 404, which a naive error mapping turns into "no victims" — so
    configuring the key, which is supposed to lift the rate limit, would
    instead make the tool quietly find nothing at all.
    """
    if is_pro:
        return f"{base}/victims/search?q={quote(selector, safe='')}"
    return f"{base}/searchvictims/{quote(selector, safe='')}"


async def _get(client: httpx.AsyncClient, url: str,
               empty_on_404: bool = False) -> tuple[Any, str | None]:
    """Returns (payload, error).

    A 429 is mapped to an explicit note about the keyless tier's
    one-per-minute limit, because "rate limited" without the remedy just
    looks like the tool is broken.

    A 404 is only "nothing found" where the caller says so — a lookup of a
    group that does not exist. On a search route a 404 means the route is
    wrong, and reporting that as an empty result set is how a broken
    integration passes for a clean run.
    """
    try:
        r = await client.get(url)
    except httpx.TimeoutException:
        return None, f"ransomware_watch: timeout ({TIMEOUT}s)"
    except httpx.HTTPError as e:
        return None, f"ransomware_watch: unreachable: {e}"
    if r.status_code == 429:
        return None, (f"{NOTE_PREFIX}ransomware_watch: rate-limited. The keyless "
                      "API allows one request per minute per endpoint; a free key "
                      "from https://my.ransomware.live removes the limit "
                      "(set RANSOMWARE_LIVE_API_KEY in Settings).")
    if r.status_code in (401, 403):
        return None, ("ransomware_watch: the configured API key was refused "
                      f"(HTTP {r.status_code}). Check it in Settings — the tool "
                      "runs keyless without one.")
    if r.status_code == 404:
        if empty_on_404:
            return [], None
        return None, f"ransomware_watch: HTTP 404 for {url.split('?')[0]}"
    if r.status_code != 200:
        return None, f"ransomware_watch: HTTP {r.status_code}"
    try:
        return r.json(), None
    except ValueError:
        return None, "ransomware_watch: non-JSON response"


def _victim_findings(
    victims: list[dict], root: str,
) -> tuple[list[Finding], list[EdgeResult]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    groups: set[str] = set()

    for v in victims[:MAX_VICTIMS]:
        name = str(v.get("victim") or "").strip()
        group = str(v.get("group") or "").strip()
        if not name:
            continue
        domain = str(v.get("domain") or "").strip().lower()
        attack = v.get("attackdate") or v.get("discovered")

        findings.append(Finding(
            entity_type="ransomware_victim", label=name, platform=group or None,
            url=v.get("post_url") or v.get("url") or v.get("claim_url") or None,
            confidence=0.85,
            # When the leak site posted it, not when we looked. For a victim
            # listing that date IS the fact — it dates the attack.
            found_at=_as_dt(attack),
            data={
                "group": group,
                "attack_date": attack,
                "country": v.get("country"),
                "sector": v.get("activity"),
                "victim_domain": domain,
                "ransom": v.get("ransom"),
                "data_size": v.get("data_size"),
                "screenshot": v.get("screenshot"),
                "press": v.get("press"),
                "source": "ransomware.live",
            },
        ))

        if group:
            edges.append(EdgeResult(
                from_entity=f"ransomware_group:{group}",
                to_entity=f"ransomware_victim:{name}",
                relation="claimed_victim", confidence=0.85,
            ))
            groups.add(group)
        if domain:
            # Tie the victim to its domain so the case graph joins up with
            # whatever infra work has already been done on that domain.
            findings.append(Finding(
                entity_type="domain", label=domain, confidence=0.8,
                data={"role": "ransomware victim", "group": group,
                      "source": "ransomware.live"},
            ))
            edges.append(EdgeResult(
                from_entity=f"ransomware_victim:{name}",
                to_entity=f"domain:{domain}",
                relation="victim_domain", confidence=0.8,
            ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"ransomware_victim:{name}",
            relation="leak_site_match", confidence=0.8,
        ))

    for group in sorted(groups):
        findings.append(Finding(
            entity_type="ransomware_group", label=group, confidence=0.9,
            url=f"https://www.ransomware.live/group/{group}",
            data={"source": "ransomware.live"},
        ))
    return findings, edges


async def run_ransomware(
    query: str, query_type: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    selector = (query or "").strip()
    if not selector:
        return [], [], ["ransomware_watch: empty query"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    base, headers, is_pro = _base_and_headers(options)
    root = f"{query_type}:{selector}"

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers,
                                 follow_redirects=True) as client:
        victims, err = await _get(
            client, _victim_search_url(base, selector, is_pro))
        if err:
            errors.append(err)
        elif isinstance(victims, list) and victims:
            f, e = _victim_findings(victims, root)
            findings.extend(f)
            edges.extend(e)
            if len(victims) > MAX_VICTIMS:
                errors.append(f"{NOTE_PREFIX}ransomware_watch: {len(victims)} victims "
                              f"matched, {MAX_VICTIMS} returned.")

        # A free-text search may well BE a group name; check that too, but do
        # not spend the rate-limit budget on it for a domain lookup.
        if query_type == "keyword":
            group, gerr = await _get(client, f"{base}/group/{quote(selector.lower(), safe='')}",
                                     empty_on_404=True)
            if gerr and NOTE_PREFIX not in gerr:
                errors.append(gerr)
            elif isinstance(group, dict) and group.get("name"):
                findings.append(Finding(
                    entity_type="ransomware_group",
                    label=str(group.get("name")),
                    url=f"https://www.ransomware.live/group/{group.get('name')}",
                    confidence=0.9,
                    data={
                        "description": (group.get("description") or "")[:1500],
                        "first_seen": group.get("added_date"),
                        "meta": group.get("meta"),
                        "profile": group.get("profile"),
                        "source": "ransomware.live",
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=root,
                    to_entity=f"ransomware_group:{group.get('name')}",
                    relation="matches_group", confidence=0.85,
                ))
                # Leak-site onions are the pivot into the darknet module.
                for loc in group.get("locations") or []:
                    onion = str((loc or {}).get("fqdn") or "").strip().lower()
                    if not onion.endswith(".onion"):
                        continue
                    findings.append(Finding(
                        entity_type="onion_service", label=onion, confidence=0.85,
                        data={"role": "ransomware leak site",
                              "group": group.get("name"),
                              "available": (loc or {}).get("available"),
                              "source": "ransomware.live"},
                    ))
                    edges.append(EdgeResult(
                        from_entity=f"ransomware_group:{group.get('name')}",
                        to_entity=f"onion_service:{onion}",
                        relation="operates_leak_site", confidence=0.85,
                    ))

    if not findings and not errors:
        errors.append(f"No ransomware leak-site entries for '{selector}'")
    return findings, edges, errors
