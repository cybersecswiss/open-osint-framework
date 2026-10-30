"""
Ethereum address lookup via Etherscan v2 API.
Requires ETHERSCAN_API_KEY (free tier at https://etherscan.io/apis).
"""
from __future__ import annotations

import os
import re

import httpx

from schemas import EdgeResult, Finding, credential

# Etherscan v2 unified endpoint. v1 (api.etherscan.io/api) is being
# sunset; v2 takes the same module/action params plus a chainid
# (1 = Ethereum mainnet).
API_URL = "https://api.etherscan.io/v2/api"
ETH_CHAIN_ID = "1"
USER_AGENT = "OOF/1.0"
WEI_PER_ETH = 10**18

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


async def run_eth_lookup(addr: str, options: dict | None = None) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    if not ETH_ADDR_RE.match(addr.strip()):
        return [], [], [f"ETH: '{addr}' is not a valid Ethereum address"]
    key = credential(options, "ETHERSCAN_API_KEY")
    if not key:
        return [], [], [
            "Etherscan: ETHERSCAN_API_KEY not set in .env "
            "(free tier at https://etherscan.io/apis)"
        ]

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    addr = addr.strip().lower()
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            bal_r = await client.get(API_URL, params={
                "chainid": ETH_CHAIN_ID,
                "module": "account", "action": "balance", "address": addr,
                "tag": "latest", "apikey": key,
            })
            tx_r = await client.get(API_URL, params={
                "chainid": ETH_CHAIN_ID,
                "module": "account", "action": "txlist", "address": addr,
                "startblock": "0", "endblock": "99999999", "page": "1",
                "offset": "20", "sort": "desc", "apikey": key,
            })
    except httpx.TimeoutException:
        return [], [], ["Etherscan timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"Etherscan error: {e}"]

    if bal_r.status_code != 200:
        return [], [], [f"Etherscan balance HTTP {bal_r.status_code}"]
    bal_data = bal_r.json()
    if str(bal_data.get("status")) != "1":
        return [], [], [f"Etherscan balance: {bal_data.get('message')}"]
    balance_eth = int(bal_data.get("result") or 0) / WEI_PER_ETH

    tx_data = tx_r.json() if tx_r.status_code == 200 else {}
    txs = tx_data.get("result") if isinstance(tx_data.get("result"), list) else []

    findings = [Finding(
        entity_type="eth_address",
        platform="etherscan",
        # Full address as the label — see the note in blockchain_runner.
        # addr is already lowercased above, so this also matches the root node.
        label=addr,
        url=f"https://etherscan.io/address/{addr}",
        confidence=0.95,
        data={
            "address": addr, "balance_eth": balance_eth,
            "tx_count_sample": len(txs), "source": "etherscan",
        },
    )]
    edges: list[EdgeResult] = []
    counterparties: set[str] = set()
    for tx in txs:
        for fld in ("from", "to"):
            ca = (tx.get(fld) or "").lower()
            if ca and ca != addr:
                counterparties.add(ca)
    for ca in list(counterparties)[:30]:
        edges.append(EdgeResult(
            from_entity=f"eth_address:{addr}",
            to_entity=f"eth_address:{ca}",
            relation="transacted_with",
            confidence=0.7,
        ))
    return findings, edges, []
