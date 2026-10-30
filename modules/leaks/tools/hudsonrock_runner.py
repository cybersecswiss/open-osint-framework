"""
Hudson Rock (Cavalier) infostealer lookup.

Where classic breach lookups (HIBP/LeakCheck) surface OLD credential dumps,
Hudson Rock surfaces the MODERN reality: machines infected by infostealer
malware (RedLine, Lumma, Raccoon, Vidar …) and the credentials/cookies that
were exfiltrated from them. For a cybercrime investigation this is often the
bridge from an anonymous email/username to a real, infected machine and to
the victim's/actor's other logins.

The free "osint-tools" endpoints are KEYLESS (rate-limited) and already give
the infection summary + top services — that is what this runner uses. An
optional operator-global HUDSONROCK_API_KEY (Cavalier full API) raises the
limits / unlocks fuller detail and is sent as `api-key` when present; the
tool works without it.

Graph convention (see graph_builder): a Finding's `label` carries the
`{entity_type}:` prefix and each edge endpoint is the same `etype:label`
string, so nodes dedupe canonically. The root is `f"{query_type}:{query}"`,
matching what the other leaks tools emit.

Privacy note (nDSG / GDPR): infostealer records contain third-party
victim PII. This runner deliberately emits the infection *facts* (machine,
date, malware, aggregate service counts) and NOT one node per stolen
credential — fine-grained credential expansion belongs behind the
sensitive-tool gate, not in the default fan-out.
"""
from __future__ import annotations

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

API_BASE = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools"
TIMEOUT = 25.0


def _headers(options: dict | None) -> dict:
    key = credential(options, "HUDSONROCK_API_KEY")
    h = {"User-Agent": "OOF/1.0", "Accept": "application/json"}
    if key:
        h["api-key"] = key
    return h


async def run_hudsonrock(
    query: str, query_type: str, options: dict | None = None
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    q = (query or "").strip()
    if not q:
        return findings, edges, ["Empty query."]

    ep = {
        "email": ("search-by-email", "email"),
        "username": ("search-by-username", "username"),
        "domain": ("search-by-domain", "domain"),
    }.get(query_type)
    if not ep:
        return findings, edges, [f"hudsonrock: unsupported query_type {query_type}"]
    endpoint, param = ep
    root = f"{query_type}:{q}"  # matches the search root node

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{API_BASE}/{endpoint}",
                            params={param: q}, headers=_headers(options))
    except httpx.HTTPError as e:
        return findings, edges, [f"hudsonrock unreachable: {type(e).__name__}: {e}"]

    if r.status_code == 429:
        return findings, edges, [NOTE_PREFIX + "Hudson Rock rate-limited (429) — set HUDSONROCK_API_KEY for higher limits."]
    if r.status_code != 200:
        return findings, edges, [f"hudsonrock HTTP {r.status_code}"]

    try:
        data = r.json() or {}
    except ValueError:
        return findings, edges, ["hudsonrock returned non-JSON."]

    if query_type in ("email", "username"):
        _parse_identity(root, data, findings, edges)
    else:
        _parse_domain(q, root, data, findings, edges)

    if not findings:
        errors.append(NOTE_PREFIX + f"No infostealer records for {q} in Hudson Rock.")
    return findings, edges, errors


# Hudson Rock fills redacted or absent fields with the literal string
# "Not Found" rather than null. Taken at face value that produces findings
# named `Not Found (<date>)` — a redaction rendered as a fact, which would
# then travel into the PDF report and any exported STIX bundle.
#
# `null` is the honest representation of "we were not told". Anything the
# API says it does not have becomes None here, at the boundary, so nothing
# downstream has to know this quirk.
_ABSENT = {"not found", "n/a", "na", "none", "null", "unknown", "-", ""}


def _v(value):
    """A field value, or None if the source said it has none."""
    if isinstance(value, str) and value.strip().lower() in _ABSENT:
        return None
    return value


def _parse_identity(root, data, findings, edges):
    """email/username → list of stealer infections under `stealers`."""
    stealers = data.get("stealers") or []
    if not isinstance(stealers, list):
        return
    seen: set[str] = set()
    for i, s in enumerate(stealers):
        if not isinstance(s, dict):
            continue
        machine = (_v(s.get("computer_name")) or _v(s.get("machine_id"))
                   or f"infection-{i+1}")
        date = _v(s.get("date_compromised")) or _v(s.get("date_uploaded"))
        disp = machine + (f" ({date[:10]})" if isinstance(date, str) and date else "")
        # keep the canonical label unique if machine names repeat
        if disp in seen:
            disp = f"{disp} #{i+1}"
        seen.add(disp)
        node = f"stealer_infection:{disp}"
        findings.append(Finding(
            entity_type="stealer_infection",
            platform="hudsonrock",
            label=node,
            confidence=0.85,
            data={
                "computer_name": machine,
                "date_compromised": date,
                "operating_system": _v(s.get("operating_system")),
                "malware_path": _v(s.get("malware_path")),
                "malware_family": _v(s.get("stealer_family")) or _v(s.get("malware")),
                "ip": _v(s.get("ip")),
                "antiviruses": s.get("antiviruses"),
                "total_corporate_services": s.get("total_corporate_services"),
                "total_user_services": s.get("total_user_services"),
                # aggregate service list only — NOT the plaintext passwords
                "top_logins": (s.get("top_logins") or [])[:15],
                "top_passwords_count": len(s.get("top_passwords") or []),
                "source": "hudsonrock",
            },
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=node,
            relation="compromised_by", confidence=0.85,
        ))


def _parse_domain(q, root, data, findings, edges):
    """domain → aggregate exposure (employees/users/third-parties infected)."""
    total = data.get("total") or data.get("totalStealers")
    stats = {
        "employees": data.get("employees") or data.get("total_employees"),
        "users": data.get("users") or data.get("total_users"),
        "third_parties": data.get("third_parties"),
        "total_stealers": total,
    }
    if not any(v for v in stats.values()):
        return
    node = f"stealer_infection:Infostealer exposure: {q}"
    findings.append(Finding(
        entity_type="stealer_infection",
        platform="hudsonrock",
        label=node,
        confidence=0.8,
        data={**stats, "domain": q, "source": "hudsonrock",
              "note": "Aggregate exposure. Pivot individual emails for machine-level detail."},
    ))
    edges.append(EdgeResult(
        from_entity=root, to_entity=node,
        relation="compromised_by", confidence=0.8,
    ))
