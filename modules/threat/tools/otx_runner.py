"""AlienVault/LevelBlue OTX — the campaign an indicator belongs to.

Every other threat tool we have answers "is this indicator bad?".
ThreatFox, URLhaus, MalwareBazaar, AbuseIPDB, C2IntelFeeds and
ioc_reputation all return a verdict about ONE value. None of them answers the
question an investigator asks next: **what else belongs to the same thing?**

OTX organises indicators into *pulses* — named bundles an author publishes
around one campaign, actor or malware family, with a description, tags,
references and every indicator they saw together. Hitting a pulse turns a
lone IP into "this address appears in a campaign that also used these three
domains and this hash", which is a lead rather than a label.

Key-gated (free). Without a key the tool says so and stops, rather than
silently returning nothing — an empty result and an unconfigured source must
never look alike.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

log = logging.getLogger("module-threat")

BASE = "https://otx.alienvault.com/api/v1/indicators"
TIMEOUT = 25.0
MAX_PULSES = 12
MAX_RELATED = 8

# query_type -> (OTX indicator section, OTX type path)
_ROUTE = {
    "ip": "IPv4",
    "domain": "domain",
    "url": "url",
    "hash": "file",
}


# An actor name is short and has no sentence in it. Everything else is the
# author writing prose into a name field — measured, not assumed.
_MAX_ACTOR_LEN = 40


def _actor_name(value) -> str:
    v = str(value or "").strip().strip(".")
    if not v or len(v) > _MAX_ACTOR_LEN:
        return ""
    if v.count(" ") > 3:            # "assumed part of the … network" and friends
        return ""
    return v


async def _get(client: httpx.AsyncClient, url: str, key: str) -> tuple[dict | None, str | None]:
    try:
        r = await client.get(url, headers={"X-OTX-API-KEY": key})
    except httpx.HTTPError as e:
        return None, f"otx: {type(e).__name__}"
    if r.status_code in (401, 403):
        return None, "otx: the API key was rejected."
    if r.status_code == 404:
        return {}, None                    # OTX says "nothing known" with a 404
    if r.status_code != 200:
        return None, f"otx: HTTP {r.status_code}"
    # Content-type is checked before parsing: several threat-intel APIs answer
    # an unknown path with 200 + an HTML page, and a bare status check would
    # then hand HTML to the JSON parser or, worse, report "no hits".
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        return None, f"otx: expected JSON, got {ctype or 'no content-type'}."
    try:
        return r.json(), None
    except ValueError:
        return None, "otx: response was not valid JSON."


async def run_otx(
    query: str, query_type: str = "ip", job_id: str = "adhoc",
    options: dict | None = None,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "OTX_API_KEY")
    if not key:
        return [], [], ["otx: no OTX_API_KEY configured. Get a free key at "
                        "https://otx.alienvault.com/api and add it under "
                        "Settings -> API keys -> Threat Intel."]

    section = _ROUTE.get(query_type)
    if not section:
        return [], [], [f"otx: unsupported selector type '{query_type}'."]

    selector = (query or "").strip()
    if not selector:
        return [], [], ["otx: empty selector."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    root = f"{query_type}:{selector}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        data, err = await _get(
            client,
            f"{BASE}/{section}/{quote(selector, safe='')}/general", key)
        if err:
            return [], [], [err]

        pulses = ((data or {}).get("pulse_info") or {}).get("pulses") or []
        if not pulses:
            return [], [], [f"{NOTE_PREFIX}otx: indicator is not part of any "
                            f"published pulse."]

        if len(pulses) > MAX_PULSES:
            errors.append(f"{NOTE_PREFIX}otx: {len(pulses)} pulses found, "
                          f"showing the {MAX_PULSES} most recent.")
            pulses = sorted(pulses, key=lambda p: str(p.get("modified") or ""),
                            reverse=True)[:MAX_PULSES]

        for p in pulses:
            name = str(p.get("name") or "").strip() or "(unnamed pulse)"
            pid = str(p.get("id") or "")
            findings.append(Finding(
                entity_type="campaign", platform="otx", label=name,
                url=f"https://otx.alienvault.com/pulse/{pid}" if pid else None,
                # A pulse is a community assertion, not a vendor verdict: an
                # author grouped these indicators. Useful as a lead, and rated
                # as one.
                confidence=0.6,
                data={
                    "pulse_id": pid,
                    "author": (p.get("author_name") or ""),
                    "description": str(p.get("description") or "")[:600],
                    "tags": (p.get("tags") or [])[:12],
                    "malware_families": [f.get("display_name")
                                         for f in (p.get("malware_families") or [])][:8],
                    # Kept verbatim on the campaign even when it is prose —
                    # it is still the author's attribution statement.
                    "adversary": p.get("adversary") or "",
                    "modified": p.get("modified"),
                    "indicator_count": p.get("indicator_count"),
                    "source": "otx",
                },
            ))
            edges.append(EdgeResult(from_entity=root,
                                    to_entity=f"campaign:{name}",
                                    relation="part_of_campaign", confidence=0.6))

            # The adversary and malware family are the parts an investigator
            # can actually pivot on, so they become their own nodes rather
            # than staying buried in the pulse payload.
            #
            # `adversary` is a FREE-TEXT field, and authors use it as such.
            # Measured on emotet.com: "assumed part of the emotet distribution
            # network and communication infrastructure" — 80 characters of
            # prose. Turning that into a `threat_actor` node gives the graph a
            # node nobody can pivot on and a label nobody can cite. Only
            # name-shaped values become nodes; the prose is kept on the
            # campaign, where a sentence belongs.
            adv = _actor_name(p.get("adversary"))
            if adv:
                findings.append(Finding(
                    entity_type="threat_actor", platform="otx", label=adv,
                    confidence=0.55, data={"source": "otx", "via_pulse": name},
                ))
                edges.append(EdgeResult(from_entity=f"campaign:{name}",
                                        to_entity=f"threat_actor:{adv}",
                                        relation="attributed_to", confidence=0.55))
            for fam in (p.get("malware_families") or [])[:MAX_RELATED]:
                fname = str(fam.get("display_name") or "").strip()
                if fname:
                    findings.append(Finding(
                        entity_type="malware", platform="otx", label=fname,
                        confidence=0.6, data={"source": "otx", "via_pulse": name},
                    ))
                    edges.append(EdgeResult(from_entity=f"campaign:{name}",
                                            to_entity=f"malware:{fname}",
                                            relation="uses_malware", confidence=0.6))

    return findings, edges, errors
