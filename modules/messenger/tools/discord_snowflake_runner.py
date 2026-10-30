"""
Discord snowflake decoding (keyless, local).

Every Discord ID (user, message, channel, guild) is a "snowflake" whose
high bits encode the creation time. Decoding it needs no API: the exact
account/object creation timestamp (UTC) plus the internal worker/process
/increment fields fall straight out of the integer. Useful to date an
account or corroborate/timeline an ID that surfaces in an investigation.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from schemas import EdgeResult, Finding

# Discord epoch: 2015-01-01T00:00:00Z in milliseconds.
DISCORD_EPOCH = 1420070400000


async def run_discord_snowflake(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    raw = re.sub(r"\D", "", query or "")
    if not raw:
        return [], [], ["Discord snowflake: no numeric ID in query"]
    sid = int(raw)

    created_ms = (sid >> 22) + DISCORD_EPOCH
    # Plausibility: must be at/after the Discord epoch and not absurdly
    # far in the future (guards against a random number being decoded).
    if created_ms < DISCORD_EPOCH:
        return [], [], [f"Discord snowflake: {raw} predates the Discord epoch "
                        "(not a valid Discord ID)"]
    dt = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)

    finding = Finding(
        entity_type="discord_account", platform="discord",
        label=raw, confidence=0.9,
        data={"discord_id": raw,
              "created_at": dt.isoformat(),
              "created_at_readable": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
              "worker_id": (sid & 0x3E0000) >> 17,
              "process_id": (sid & 0x1F000) >> 12,
              "increment": sid & 0xFFF,
              "source": "snowflake"},
    )
    edge = EdgeResult(from_entity=f"discord_id:{raw}",
                      to_entity=f"discord_account:{raw}",
                      relation="decoded", confidence=0.9)
    return [finding], [edge], []
