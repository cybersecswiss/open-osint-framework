"""
Discord invite resolve.

Hits the public, unauthenticated Discord API endpoint
GET https://discord.com/api/v10/invites/<code>?with_counts=true.
Returns the guild (server) name, ID, member counts, and the channel
the invite points to. Useful for cybercrime/extremist server
fingerprinting from a posted invite link.
"""
from __future__ import annotations

import re

import httpx

from schemas import EdgeResult, Finding

API_URL = "https://discord.com/api/v10/invites/{code}"
USER_AGENT = "OOF/1.0"

CODE_RE = re.compile(r"^[A-Za-z0-9-]{2,32}$")


def _extract_code(query: str) -> str | None:
    q = query.strip()
    for prefix in ("https://discord.gg/", "http://discord.gg/",
                   "https://discord.com/invite/", "http://discord.com/invite/"):
        if q.startswith(prefix):
            q = q[len(prefix):]
            break
    q = q.split("?", 1)[0].split("/", 1)[0]
    return q if CODE_RE.match(q) else None


async def run_discord_invite(query: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    code = _extract_code(query)
    if not code:
        return [], [], [f"Discord: invalid invite '{query}' "
                        "(expected discord.gg/<code> or just <code>)"]
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            r = await client.get(API_URL.format(code=code),
                                 params={"with_counts": "true"})
            if r.status_code == 404:
                return [], [], [f"Discord invite {code} expired or invalid"]
            if r.status_code == 429:
                return [], [], ["Discord: rate-limited (HTTP 429)"]
            if r.status_code != 200:
                return [], [], [f"Discord HTTP {r.status_code}"]
            data = r.json()
    except httpx.TimeoutException:
        return [], [], ["Discord timeout (15s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"Discord error: {e}"]

    guild = data.get("guild") or {}
    channel = data.get("channel") or {}
    inviter = data.get("inviter") or {}

    findings: list[Finding] = [Finding(
        entity_type="discord_guild",
        platform="discord",
        label=guild.get("name") or code,
        url=f"https://discord.gg/{code}",
        confidence=0.95,
        data={
            "invite_code": code,
            "guild_id": guild.get("id"),
            "guild_name": guild.get("name"),
            "guild_description": guild.get("description"),
            "channel_name": channel.get("name"),
            "channel_id": channel.get("id"),
            "approximate_member_count": data.get("approximate_member_count"),
            "approximate_presence_count": data.get("approximate_presence_count"),
            "verification_level": guild.get("verification_level"),
            "nsfw_level": guild.get("nsfw_level"),
            "vanity_url_code": guild.get("vanity_url_code"),
            "source": "discord",
        },
    )]
    edges: list[EdgeResult] = []
    if inviter.get("username"):
        findings.append(Finding(
            entity_type="discord_user",
            platform="discord",
            label=f"discord/{inviter['username']}",
            url=f"https://discord.com/users/{inviter.get('id', '')}",
            confidence=0.9,
            data={"username": inviter["username"], "user_id": inviter.get("id"),
                  "global_name": inviter.get("global_name"),
                  "source": "discord"},
        ))
        edges.append(EdgeResult(
            from_entity=f"discord_user:{inviter['username']}",
            to_entity=f"discord_guild:{guild.get('id') or code}",
            relation="invited_to",
            confidence=0.9,
        ))
    return findings, edges, []
