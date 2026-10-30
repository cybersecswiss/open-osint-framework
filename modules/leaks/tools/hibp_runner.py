"""
HaveIBeenPwned v3 breach lookup. Requires a paid API key
(https://haveibeenpwned.com/API/Key — $3.95/mo). Without one we
return a clear instruction to register, plus a deep-link the user
can open manually.
"""
from __future__ import annotations

import os

import httpx

from schemas import EdgeResult, Finding, credential

API_BASE = "https://haveibeenpwned.com/api/v3"
USER_AGENT = "OOF/1.0"


async def run_hibp(email: str, options: dict | None = None) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "HIBP_API_KEY")
    if not key:
        return (
            [Finding(
                entity_type="search_link",
                platform="hibp",
                label=f"hibp:{email}",
                url=f"https://haveibeenpwned.com/account/{email}",
                confidence=0.5,
                data={
                    "note": "HIBP_API_KEY not set — manual lookup link returned",
                    "register_at": "https://haveibeenpwned.com/API/Key",
                },
            )],
            # Anchor the deep-link to the email entity so it stays
            # connected in the graph instead of floating.
            [EdgeResult(
                from_entity=f"email:{email}",
                to_entity=f"search_link:hibp:{email}",
                relation="search_link_for",
                confidence=0.5,
            )],
            ["HIBP: HIBP_API_KEY not set in .env"],
        )

    headers = {"hibp-api-key": key, "User-Agent": USER_AGENT,
               "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(
                f"{API_BASE}/breachedaccount/{email}",
                params={"truncateResponse": "false"},
            )
            if r.status_code == 404:
                return [], [], []  # no breaches — clean negative
            if r.status_code == 401:
                return [], [], ["HIBP: HTTP 401 — API key rejected"]
            if r.status_code == 429:
                return [], [], ["HIBP: rate-limited (HTTP 429)"]
            if r.status_code != 200:
                return [], [], [f"HIBP HTTP {r.status_code}"]
            breaches = r.json() or []
    except httpx.TimeoutException:
        return [], [], ["HIBP timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"HIBP error: {e}"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    for b in breaches:
        name = b.get("Name") or "?"
        findings.append(Finding(
            entity_type="breach",
            platform="hibp",
            label=f"breach:{name}",
            url=f"https://haveibeenpwned.com/PwnedWebsites#{name}",
            confidence=0.95,
            data={
                "name": name, "title": b.get("Title"),
                "breach_date": b.get("BreachDate"),
                "pwn_count": b.get("PwnCount"),
                "data_classes": b.get("DataClasses") or [],
                "is_verified": b.get("IsVerified"),
                "is_sensitive": b.get("IsSensitive"),
                "source": "hibp",
            },
        ))
        edges.append(EdgeResult(
            from_entity=f"email:{email}",
            to_entity=f"breach:{name}",
            relation="appears_in_breach",
            confidence=0.95,
        ))
    return findings, edges, []
