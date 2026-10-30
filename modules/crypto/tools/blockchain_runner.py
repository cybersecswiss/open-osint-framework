"""
Bitcoin address lookup via blockchain.info public API.
No key required, gracefully degrades if rate-limited.
Returns balance, total received/sent, transaction count, and the
first counterparty addresses for graph pivoting.
"""
from __future__ import annotations

import re

import httpx

from schemas import EdgeResult, Finding

API_URL = "https://blockchain.info/rawaddr/{addr}"
USER_AGENT = "OOF/1.0"
SAT_PER_BTC = 100_000_000

BTC_ADDR_RE = re.compile(r"^(bc1[a-z0-9]{8,87}|[13][A-HJ-NP-Za-km-z1-9]{25,34})$")


async def run_btc_lookup(addr: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    if not BTC_ADDR_RE.match(addr.strip()):
        return [], [], [f"BTC: '{addr}' is not a valid Bitcoin address"]
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(API_URL.format(addr=addr.strip()),
                                 params={"limit": "20"})
            if r.status_code == 429:
                return [], [], ["blockchain.info: rate-limited (HTTP 429)"]
            if r.status_code == 404:
                return [], [], [f"blockchain.info: address {addr} not found"]
            if r.status_code != 200:
                return [], [], [f"blockchain.info HTTP {r.status_code}"]
            data = r.json()
    except httpx.TimeoutException:
        return [], [], ["blockchain.info timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"blockchain.info error: {e}"]

    final_balance = (data.get("final_balance") or 0) / SAT_PER_BTC
    total_received = (data.get("total_received") or 0) / SAT_PER_BTC
    total_sent = (data.get("total_sent") or 0) / SAT_PER_BTC
    n_tx = data.get("n_tx") or 0

    findings = [Finding(
        entity_type="btc_address",
        platform="blockchain.info",
        # Full address as the label: it is this node's identity. A truncated
        # label made the finding key ("btc_address:btc:1A1zP1eP5Q…") differ
        # from the edge endpoint ("btc_address:<full addr>"), so the data node
        # and the transaction edges ended up on two separate nodes.
        label=addr,
        url=f"https://www.blockchain.com/btc/address/{addr}",
        confidence=0.95,
        data={
            "address": addr, "balance_btc": final_balance,
            "total_received_btc": total_received, "total_sent_btc": total_sent,
            "tx_count": n_tx, "source": "blockchain.info",
        },
    )]
    edges: list[EdgeResult] = []
    counterparties: set[str] = set()
    for tx in (data.get("txs") or [])[:10]:
        for inp in tx.get("inputs", []) or []:
            ca = ((inp.get("prev_out") or {}).get("addr"))
            if ca and ca != addr:
                counterparties.add(ca)
        for out in tx.get("out", []) or []:
            ca = out.get("addr")
            if ca and ca != addr:
                counterparties.add(ca)
    for ca in list(counterparties)[:30]:
        edges.append(EdgeResult(
            from_entity=f"btc_address:{addr}",
            to_entity=f"btc_address:{ca}",
            relation="transacted_with",
            confidence=0.7,
        ))
    return findings, edges, []
