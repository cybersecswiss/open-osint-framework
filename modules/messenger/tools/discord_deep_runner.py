"""Discord deep profile (CordCat-style) — user ID → full PUBLIC profile via
the official ``GET /users/{id}`` endpoint with the operator's bot token.

ToS-compliant and read-only: it's the same endpoint any bot uses to look up
a user. Returns username, global (display) name, avatar/banner CDN URLs,
accent colour, bot/system flags and the badges decoded from ``public_flags``
— plus the creation date that falls straight out of the snowflake. No
message history, no mutual-guild scraping (those need a user token / violate
ToS). Key-gated: without ``DISCORD_BOT_TOKEN`` the keyless snowflake tool
still dates the account.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from schemas import EdgeResult, Finding, credential

DISCORD_EPOCH = 1420070400000
API = "https://discord.com/api/v10"
CDN = "https://cdn.discordapp.com"

# public_flags bit → badge name (Discord's documented user flags).
FLAGS = {
    1 << 0:  "Discord Staff",
    1 << 1:  "Partnered Server Owner",
    1 << 2:  "HypeSquad Events",
    1 << 3:  "Bug Hunter Level 1",
    1 << 6:  "HypeSquad Bravery",
    1 << 7:  "HypeSquad Brilliance",
    1 << 8:  "HypeSquad Balance",
    1 << 9:  "Early Supporter",
    1 << 10: "Team Pseudo User",
    1 << 14: "Bug Hunter Level 2",
    1 << 16: "Verified Bot",
    1 << 17: "Early Verified Bot Developer",
    1 << 18: "Moderator Programs Alumni",
    1 << 22: "Active Developer",
}


def _created(sid: int) -> datetime:
    return datetime.fromtimestamp(((sid >> 22) + DISCORD_EPOCH) / 1000, tz=timezone.utc)


def _badges(flags: int) -> list[str]:
    return [name for bit, name in FLAGS.items() if flags & bit]


def _avatar_url(uid: str, avatar: str | None) -> str | None:
    if not avatar:
        return None
    ext = "gif" if avatar.startswith("a_") else "png"
    return f"{CDN}/avatars/{uid}/{avatar}.{ext}?size=512"


def _banner_url(uid: str, banner: str | None) -> str | None:
    if not banner:
        return None
    ext = "gif" if banner.startswith("a_") else "png"
    return f"{CDN}/banners/{uid}/{banner}.{ext}?size=1024"


async def run_discord_deep(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    uid = re.sub(r"\D", "", query or "")
    if not uid:
        return [], [], ["Discord deep: no numeric user ID in query."]
    if (int(uid) >> 22) + DISCORD_EPOCH < DISCORD_EPOCH:
        return [], [], [f"Discord deep: {uid} is not a valid Discord snowflake."]

    token = credential(options, "DISCORD_BOT_TOKEN")
    if not token:
        return [], [], ["Discord deep: needs a Discord bot token (Global-Admin → "
                        "Settings → Discord). The keyless 'discord_snowflake' tool "
                        "still decodes the creation date."]

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{API}/users/{uid}",
                            headers={"Authorization": f"Bot {token}"})
    except httpx.HTTPError as e:
        return [], [], [f"Discord deep: request failed: {type(e).__name__}: {e}"]

    if r.status_code == 404:
        return [], [], [f"Discord deep: no Discord user with ID {uid}."]
    if r.status_code == 401:
        return [], [], ["Discord deep: bot token rejected (401). Re-check the token."]
    if r.status_code == 429:
        return [], [], ["Discord deep: rate-limited by Discord (429) — retry shortly."]
    if r.status_code != 200:
        return [], [], [f"Discord deep: unexpected HTTP {r.status_code}."]

    u = r.json()
    created = _created(int(uid))
    flags = int(u.get("public_flags") or 0)
    username = u.get("username") or uid
    global_name = u.get("global_name")
    handle = f"@{username}" if username else uid

    data = {
        "discord_id": uid,
        "username": username,
        "global_name": global_name,
        "is_bot": bool(u.get("bot")),
        "is_system": bool(u.get("system")),
        "badges": _badges(flags),
        "public_flags": flags,
        "avatar_url": _avatar_url(uid, u.get("avatar")),
        "banner_url": _banner_url(uid, u.get("banner")),
        "accent_color": u.get("accent_color"),
        "created_at": created.isoformat(),
        "created_at_readable": created.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source": "discord_deep",
    }
    # Legacy discriminator (0 = migrated to the new username system)
    disc = u.get("discriminator")
    if disc and disc != "0":
        data["legacy_tag"] = f"{username}#{disc}"

    label = f"{username} ({uid})"
    findings = [Finding(
        entity_type="discord_account", platform="discord",
        label=label,
        url=f"https://discord.com/users/{uid}",
        confidence=0.95, data=data,
    )]
    edges = [EdgeResult(from_entity=f"discord_id:{uid}",
                        to_entity=f"discord_account:{label}",
                        relation="profile_of", confidence=0.95)]
    return findings, edges, []
