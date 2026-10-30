"""
MistTrack wallet attribution + risk scoring.

The other crypto tools answer "what is the balance / tx history". This one
answers the questions that matter for a cybercrime case: WHOSE wallet is
this and is it dirty. MistTrack returns entity labels (exchange, mixer,
known scam/ransomware cluster), a risk score, and the risk breakdown —
turning a raw address into an attribution and, crucially, a cash-out point
(a regulated exchange = a concrete subpoena / mutual-legal-assistance
target).

⚠️ **There is no free tier any more.** The MistTrack OpenAPI is available on
the Standard / Compliance / Developer plans only. A missing-key message that
says "register a free AML API key" would send the operator looking for
something that no longer exists — the one thing such a message must not do.

So this is now an OPTIONAL PAID upgrade, and the framework has a keyless
floor underneath it:

  * `address_risk` (GoPlus) — EVM addresses, keyless. Aggregates SlowMist,
    which is MistTrack's own parent company, plus BlockSec, OFAC and
    Chainabuse. Covers the "is it dirty" half.
  * `sanctions_screen` (corporate) — OFAC-designated wallets on eight
    chains, keyless, and citable as a primary source.
  * `ransomlook_crypto` (threat) — wallets attributed to a ransomware group.

What only MistTrack still gives: counterparty analysis and the cash-out
chain. Buy it if a case needs those; the trial is $10 for 48 hours.

Managed operator-side in /glbadmin → Settings.
"""
from __future__ import annotations

import re

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

API_ROOT = "https://openapi.misttrack.io"
# The two endpoints are versioned INDEPENDENTLY: risk scoring moved to v3 in
# the 2026 API revision while address labels stayed on v1. One shared base
# would silently 404 one of them.
RISK_PATH = "v3/risk_score"
LABELS_PATH = "v1/address_labels"
TIMEOUT = 25.0
BTC_RE = re.compile(r"^(bc1[a-z0-9]{6,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _coin(addr: str, query_type: str) -> str | None:
    if query_type == "eth_address" or ETH_RE.match(addr):
        return "ETH"
    if query_type == "btc_address" or BTC_RE.match(addr):
        return "BTC"
    return None


async def _get(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    r = await client.get(f"{API_ROOT}/{path}", params=params,
                         headers={"User-Agent": "OOF/1.0"})
    if r.status_code != 200:
        return {"_http": r.status_code}
    try:
        return r.json() or {}
    except ValueError:
        return {}


async def run_misttrack(
    addr: str, query_type: str, options: dict | None = None
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    a = (addr or "").strip()
    if not a:
        return findings, edges, ["Empty address."]

    key = credential(options, "MISTTRACK_API_KEY")
    if not key:
        return findings, edges, [
            f"{NOTE_PREFIX}MistTrack: no MISTTRACK_API_KEY set. This is an "
            "OPTIONAL PAID source — MistTrack retired its free tier, the "
            "OpenAPI now needs a Standard/Compliance/Developer plan "
            "(dashboard.misttrack.io/apikeys). Keyless cover for the same "
            "ground: `address_risk` for EVM risk, `sanctions_screen` for "
            "OFAC-designated wallets, `ransomlook_crypto` for "
            "ransomware-group wallets."
        ]

    coin = _coin(a, query_type)
    if not coin:
        return findings, edges, [f"MistTrack: could not determine coin for '{a}'."]

    root = f"{query_type}:{a}"
    params = {"coin": coin, "address": a, "api_key": key}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # v3 since the 2026 API revision; v1/risk_score is gone. The
            # label endpoint is still v1 — they version independently.
            risk = await _get(c, RISK_PATH, params)
            labels = await _get(c, LABELS_PATH, params)
    except httpx.HTTPError as e:
        return findings, edges, [f"MistTrack unreachable: {type(e).__name__}: {e}"]

    for resp, what in ((risk, RISK_PATH), (labels, LABELS_PATH)):
        if resp.get("_http") in (401, 403):
            return findings, edges, [f"MistTrack: key refused (HTTP {resp['_http']})."]
        if resp.get("_http") == 429:
            errors.append(NOTE_PREFIX + "MistTrack rate-limited (429).")

    rdata = (risk.get("data") or {}) if risk.get("success", True) else {}
    ldata = (labels.get("data") or {}) if labels.get("success", True) else {}
    label_list = ldata.get("label_list") or ldata.get("labels") or []
    categories = ldata.get("categories") or []
    score = rdata.get("score")
    risk_level = rdata.get("risk_level")

    if score is None and not label_list:
        errors.append(NOTE_PREFIX + f"MistTrack has no attribution for {a}.")
        return findings, edges, errors

    # Attribution / risk summary node hung off the wallet.
    node = f"wallet_label:{coin} {a[:10]}…"
    findings.append(Finding(
        entity_type="wallet_label", platform="misttrack", label=node,
        confidence=0.85,
        data={
            "coin": coin, "address": a,
            "risk_score": score, "risk_level": risk_level,
            "risk_detail": rdata.get("risk_detail") or rdata.get("detail_list"),
            "hacking_event": rdata.get("hacking_event"),
            "labels": label_list, "categories": categories,
            "source": "misttrack",
        },
    ))
    edges.append(EdgeResult(from_entity=root, to_entity=node,
                            relation="risk_assessment", confidence=0.85))

    # Named entity labels (exchanges, services) → organization nodes; a
    # cash-out at a regulated exchange is a concrete investigative target.
    for lbl in label_list:
        name = lbl if isinstance(lbl, str) else (lbl.get("label") or lbl.get("name") if isinstance(lbl, dict) else None)
        if not name or len(str(name)) < 2:
            continue
        org = f"organization:{name}"
        findings.append(Finding(
            entity_type="organization", platform="misttrack", label=org,
            confidence=0.7,
            data={"via": "misttrack_label", "coin": coin, "source": "misttrack"},
        ))
        edges.append(EdgeResult(from_entity=root, to_entity=org,
                                relation="attributed_to", confidence=0.7))

    return findings, edges, errors
