"""
Ethereum address lookup via Blockscout — the keyless ETH source.

Replaces the former Blockchair path, whose free/keyless endpoint blocks
datacenter IPs with an HTTP 430 regardless of headers. Blockscout's
public instance (eth.blockscout.com) needs no key and returns richer
data, including the cybercrime-relevant `is_scam` / `is_verified` flags.

Label + edge conventions are IDENTICAL to etherscan_runner.py
(`eth:<addr[:10]>…`, `eth_address:<addr>`), so when an Etherscan key is
also configured both tools' findings for the same address collapse to a
single graph node (dedup by (entity_type, label)) instead of duplicating.
"""
from __future__ import annotations

import re

import httpx

from schemas import EdgeResult, Finding

BASE = "https://eth.blockscout.com/api/v2/addresses"
USER_AGENT = "OOF/1.0"
WEI_PER_ETH = 10**18
MAX_COUNTERPARTIES = 30

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


async def run_blockscout(
    addr: str, query_type: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    if query_type != "eth_address":
        return [], [], [f"Blockscout: unsupported query_type={query_type}"]
    addr = addr.strip()
    if not ETH_ADDR_RE.match(addr):
        return [], [], [f"Blockscout: '{addr}' is not a valid Ethereum address"]
    addr = addr.lower()

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            info_r = await client.get(f"{BASE}/{addr}")
            if info_r.status_code == 404:
                return [], [], [f"Blockscout: address {addr} not found"]
            if info_r.status_code == 429:
                return [], [], ["Blockscout: rate-limited (HTTP 429)"]
            if info_r.status_code != 200:
                return [], [], [f"Blockscout HTTP {info_r.status_code}"]
            info = info_r.json()
            # Transactions are best-effort — the address finding is the
            # primary result and must not fail if the tx page errors.
            try:
                tx_r = await client.get(f"{BASE}/{addr}/transactions")
                tx_items = tx_r.json().get("items", []) if tx_r.status_code == 200 else []
            except Exception:  # noqa: BLE001
                tx_items = []
    except httpx.TimeoutException:
        return [], [], ["Blockscout timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"Blockscout error: {e}"]

    balance_eth = int(info.get("coin_balance") or 0) / WEI_PER_ETH
    is_scam = bool(info.get("is_scam"))
    public_tags = [t.get("label") for t in (info.get("public_tags") or []) if t.get("label")]

    findings = [Finding(
        entity_type="eth_address",
        platform="blockscout",
        label=f"eth:{addr[:10]}…",
        url=f"https://eth.blockscout.com/address/{addr}",
        # A flagged scam address is a high-confidence signal.
        confidence=0.95 if is_scam else 0.9,
        data={
            "address": addr,
            "balance_eth": balance_eth,
            "is_contract": bool(info.get("is_contract")),
            "is_scam": is_scam,
            "is_verified": bool(info.get("is_verified")),
            "ens_domain_name": info.get("ens_domain_name"),
            "name": info.get("name"),
            "public_tags": public_tags,
            "reputation": info.get("reputation"),
            "source": "blockscout",
        },
    )]

    edges: list[EdgeResult] = []
    counterparties: set[str] = set()
    for tx in tx_items:
        for fld in ("from", "to"):
            ca = ((tx.get(fld) or {}).get("hash") or "").lower()
            if ETH_ADDR_RE.match(ca) and ca != addr:
                counterparties.add(ca)
    for ca in list(counterparties)[:MAX_COUNTERPARTIES]:
        edges.append(EdgeResult(
            from_entity=f"eth_address:{addr}",
            to_entity=f"eth_address:{ca}",
            relation="transacted_with",
            confidence=0.7,
        ))
    return findings, edges, []
