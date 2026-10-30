"""
GreyNoise community lookup — free, no key required.
Returns whether an IP is part of GreyNoise's internet-scanner sensor
network and whether it's classified as benign/malicious/unknown.
"""
from __future__ import annotations

import httpx

from schemas import EdgeResult, Finding

API_URL = "https://api.greynoise.io/v3/community"
USER_AGENT = "OOF/1.0"


async def run_greynoise(ip: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            r = await client.get(f"{API_URL}/{ip}")
            if r.status_code == 404:
                return [], [], []  # IP not seen by GreyNoise — clean negative
            if r.status_code == 429:
                return [], [], ["GreyNoise: rate-limited (HTTP 429)"]
            if r.status_code != 200:
                return [], [], [f"GreyNoise HTTP {r.status_code}"]
            data = r.json()
    except httpx.TimeoutException:
        return [], [], ["GreyNoise timeout (20s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"GreyNoise error: {e}"]

    classification = data.get("classification") or "unknown"
    # Edge endpoint must equal this finding's key ("{entity_type}:{label}") —
    # see the same note in abuseipdb_runner.
    label = f"greynoise:{classification}:{ip}"
    findings = [Finding(
        entity_type="ip_reputation",
        platform="greynoise",
        label=label,
        url=f"https://viz.greynoise.io/ip/{ip}",
        confidence=0.85,
        data={
            "ip": ip,
            "noise": data.get("noise"),
            "riot": data.get("riot"),
            "classification": classification,
            "name": data.get("name", ""),
            "last_seen": data.get("last_seen"),
            "source": "greynoise",
        },
    )]
    edges = [EdgeResult(
        from_entity=f"ip:{ip}",
        to_entity=f"ip_reputation:{label}",
        relation="reputation_of",
        confidence=0.9,
    )]
    return findings, edges, []
