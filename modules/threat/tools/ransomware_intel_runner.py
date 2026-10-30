"""ransomware.live PRO — what a group leaves behind.

`ransomware_watch` answers "who did this group hit". This answers the
question that follows in an actual case: **what of theirs can I follow?**

Four PRO endpoints, all measured against the live API rather than taken
from documentation:

* `/iocs/<group>`         → md5, sha256 and **btc** addresses
* `/negotiations/<group>` → per-chat ransom demanded, negotiated, paid
* `/ransomnotes/<group>`  → the note variants attributed to the group
* `/yara/<group>`         → detection rules published for it

The BTC addresses are the reason this exists. Everything else describes the
group; a wallet is a **selector** — it goes straight into the crypto module,
and from there into transaction graphs. It is the one output here that turns
a threat-intel lookup into an investigative lead.

Negotiation chats are summarised, never reproduced: the finding carries the
demanded and negotiated amounts and whether it was paid. That is the
evidentiary substance, and it keeps the case file from filling with victim
correspondence the investigator did not ask for.

**PRO-only.** The keyless v2 tier does not serve any of this — measured:
every unknown v2 path answers HTTP 200 with an HTML page, byte-identical for
`/negotiations` and for a nonsense path. Without a key this tool says so and
stops.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

log = logging.getLogger("module-threat")

PRO = "https://api-pro.ransomware.live"
TIMEOUT = 30.0

# A group can carry 300+ hashes. All of them would bury the case; the wallets
# are few and each one is a lead, so they are never capped.
MAX_HASHES = 25
MAX_CHATS = 15
MAX_NOTES = 10


async def _get(client: httpx.AsyncClient, path: str, key: str) -> tuple[dict | None, str | None]:
    try:
        r = await client.get(f"{PRO}{path}", headers={
            "X-API-KEY": key, "Accept": "application/json",
            "User-Agent": "OOF/1.0",
        })
    except httpx.HTTPError as e:
        return None, f"{type(e).__name__}"
    if r.status_code in (401, 403):
        return None, "the PRO key was rejected"
    if r.status_code == 404:
        return {}, None
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    # Content-type before parsing. This API answers unknown paths with 200 and
    # an HTML page, so a status check alone would hand HTML to json() — or,
    # worse, let an empty parse read as "this group has nothing".
    if "json" not in r.headers.get("content-type", ""):
        return None, "expected JSON, got HTML (unknown endpoint?)"
    try:
        return r.json(), None
    except ValueError:
        return None, "response was not valid JSON"


async def run_ransomware_intel(
    query: str, query_type: str = "keyword", job_id: str = "adhoc",
    options: dict | None = None,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "RANSOMWARE_LIVE_API_KEY")
    if not key:
        return [], [], [
            "ransomware_group_intel: needs RANSOMWARE_LIVE_API_KEY (free at "
            "https://my.ransomware.live). The keyless tier does not serve "
            "IOCs, negotiations, ransom notes or YARA rules at all."]

    group = (query or "").strip().lower()
    if not group:
        return [], [], ["ransomware_group_intel: name a group."]
    slug = quote(group, safe="")
    root = f"threat_actor:{group}"

    findings: list[Finding] = [Finding(
        entity_type="threat_actor", platform="ransomware.live", label=group,
        url=f"https://www.ransomware.live/group/{group}", confidence=0.85,
        data={"source": "ransomware.live PRO"},
    )]
    edges: list[EdgeResult] = []
    errors: list[str] = []
    hits = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # ── IOCs: wallets first, they are the only pivotable output ──
        data, err = await _get(client, f"/iocs/{slug}", key)
        if err:
            errors.append(f"ransomware_group_intel: iocs — {err}")
        else:
            iocs = (data or {}).get("iocs") or {}
            for addr in (iocs.get("btc") or []):
                addr = str(addr).strip()
                if not addr:
                    continue
                hits += 1
                findings.append(Finding(
                    entity_type="btc_address", platform="ransomware.live",
                    label=addr,
                    url=f"https://www.blockchain.com/explorer/addresses/btc/{addr}",
                    confidence=0.8,
                    data={"group": group, "source": "ransomware.live PRO",
                          "role": "ransom wallet attributed to the group"},
                ))
                edges.append(EdgeResult(from_entity=root,
                                        to_entity=f"btc_address:{addr}",
                                        relation="uses_wallet", confidence=0.8))
            for kind in ("sha256", "md5"):
                vals = [str(v).strip() for v in (iocs.get(kind) or []) if str(v).strip()]
                if len(vals) > MAX_HASHES:
                    errors.append(f"{NOTE_PREFIX}ransomware_group_intel: "
                                  f"{len(vals)} {kind} hashes, showing "
                                  f"{MAX_HASHES}.")
                for h in vals[:MAX_HASHES]:
                    hits += 1
                    findings.append(Finding(
                        entity_type="hash", platform="ransomware.live", label=h,
                        confidence=0.8,
                        data={"group": group, "hash_type": kind,
                              "source": "ransomware.live PRO"},
                    ))
                    edges.append(EdgeResult(from_entity=root,
                                            to_entity=f"hash:{h}",
                                            relation="uses_malware", confidence=0.8))

        # ── Negotiations: amounts, not correspondence ────────────────
        data, err = await _get(client, f"/negotiations/{slug}", key)
        if err:
            errors.append(f"ransomware_group_intel: negotiations — {err}")
        else:
            chats = (data or {}).get("chats") or []
            if chats:
                hits += 1
                paid = sum(1 for c in chats if c.get("paid"))
                findings.append(Finding(
                    entity_type="negotiation", platform="ransomware.live",
                    label=f"{group}: {len(chats)} negotiation(s), {paid} paid",
                    url=f"https://www.ransomware.live/negotiations/{group}",
                    confidence=0.85,
                    data={
                        "group": group, "chats": len(chats), "paid": paid,
                        # A sample, not the correspondence. The amounts are the
                        # evidentiary substance; the messages are the victim's.
                        "sample": [
                            {"id": c.get("id"), "messages": c.get("message_count"),
                             "initial": c.get("initialransom"),
                             "negotiated": c.get("negotiatedransom"),
                             "paid": c.get("paid")}
                            for c in chats[:MAX_CHATS]
                        ],
                        "source": "ransomware.live PRO",
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=root,
                    to_entity=f"negotiation:{group}: {len(chats)} negotiation(s), {paid} paid",
                    relation="negotiated", confidence=0.85))
                if len(chats) > MAX_CHATS:
                    errors.append(f"{NOTE_PREFIX}ransomware_group_intel: "
                                  f"{len(chats)} chats, sampling {MAX_CHATS}.")

        # ── Ransom notes + YARA: capability, not selectors ───────────
        for path, field, label, rel in (
            (f"/ransomnotes/{slug}", "ransomnotes", "ransom note", "publishes_note"),
            (f"/yara/{slug}", "rules", "YARA rule", "detected_by"),
        ):
            data, err = await _get(client, path, key)
            if err:
                errors.append(f"ransomware_group_intel: {label} — {err}")
                continue
            items = (data or {}).get(field) or []
            if not items:
                continue
            hits += 1
            names = [str(i if isinstance(i, str) else i.get("name") or i).strip()
                     for i in items][:MAX_NOTES]
            findings.append(Finding(
                entity_type="artifact", platform="ransomware.live",
                label=f"{group}: {len(items)} {label}(s)", confidence=0.8,
                data={"group": group, "kind": label, "count": len(items),
                      "names": names, "source": "ransomware.live PRO"},
            ))
            edges.append(EdgeResult(
                from_entity=root,
                to_entity=f"artifact:{group}: {len(items)} {label}(s)",
                relation=rel, confidence=0.8))

    if hits == 0 and not errors:
        return [], [], [f"{NOTE_PREFIX}ransomware_group_intel: nothing published "
                        f"for '{group}' — check the spelling against the group "
                        f"list on ransomware.live."]
    return findings, edges, errors
