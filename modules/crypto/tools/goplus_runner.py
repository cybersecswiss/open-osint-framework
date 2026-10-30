"""Address risk for EVM chains — GoPlus, keyless.

## Why this exists

`wallet_attribution` (MistTrack) answered "whose wallet is this and is it
dirty". **MistTrack's free tier no longer exists**: the OpenAPI is
Standard/Compliance/Developer only, so on an instance without a paid key
that question would go unanswered entirely.

GoPlus answers most of it for nothing, and from the same well: its
`data_source` field returns **SlowMist** — the company behind MistTrack —
alongside BlockSec, and it folds in OFAC and Chainabuse. No key, no
registration.

Seventeen risk dimensions, of which these carry a cybercrime case:

    sanctioned · mixer · money_laundering · financial_crime · cybercrime
    darkweb_transactions · blackmail_activities · stealing_attack
    phishing_activities · malicious_mining_activities · blacklist_doubt
    honeypot_related_address · fake_kyc

## ⚠️ EVM ONLY — and this is the whole design constraint

Measured against the live API: a Bitcoin address returns
**HTTP 200 with every flag at "0" and an empty `data_source`** — the Bitcoin
genesis address and a known Akira ransomware wallet both came back looking
pristine. That is not a clean result, it is *no coverage*, and the two are
indistinguishable in the response body.

For an investigative tool that is the most dangerous failure there is: it
does not error, it reassures. So this runner **refuses non-EVM addresses
before making the request** and says why. A BTC address belongs in
`sanctions_screen` (OFAC designates 252 of them) or `ransomlook_crypto`.

The same trap explains why an all-zero EVM answer is reported as a note
rather than silently returning nothing: "GoPlus knows nothing about this
address" is a different statement from "this address is clean", and the
analyst has to be the one who decides what that is worth.
"""
from __future__ import annotations

import logging
import re

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX

API = "https://api.gopluslabs.io/api/v1/address_security"
TIMEOUT = 25.0
# Ethereum mainnet. GoPlus keys its index by chain, but the malicious-address
# dataset is shared across EVM chains, so mainnet is the right default and
# the flags returned are not chain-specific.
CHAIN_ID = "1"
EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

log = logging.getLogger("module-crypto.goplus")

# flag -> (label, weight). The weight is only used to order what the analyst
# reads first; it is deliberately NOT summed into a score. A single number
# would invite the same misreading the Admiralty scale exists to prevent —
# `sanctioned` is a legal fact and `blacklist_doubt` is a suspicion, and no
# arithmetic makes those commensurable.
FLAGS: dict[str, tuple[str, int]] = {
    "sanctioned": ("on a sanctions list", 100),
    "money_laundering": ("money laundering", 90),
    "blackmail_activities": ("extortion / blackmail", 90),
    "stealing_attack": ("theft / drainer", 85),
    "darkweb_transactions": ("darknet transactions", 80),
    "cybercrime": ("cybercrime", 80),
    "financial_crime": ("financial crime", 75),
    "mixer": ("mixer / tumbler", 70),
    "phishing_activities": ("phishing", 70),
    "malicious_mining_activities": ("malicious mining", 60),
    "fake_kyc": ("fake KYC", 55),
    "honeypot_related_address": ("honeypot-related", 50),
    "number_of_malicious_contracts_created": ("deployed malicious contracts", 50),
    "gas_abuse": ("gas abuse", 40),
    "fake_token": ("fake token", 40),
    "fake_standard_interface": ("fake standard interface", 35),
    "reinit": ("reinitialisation risk", 30),
    "blacklist_doubt": ("flagged on a blocklist", 30),
}


def _raised(result: dict) -> list[tuple[str, str, int]]:
    """(key, label, weight) for every flag the API set, strongest first."""
    out = []
    for key, (label, weight) in FLAGS.items():
        raw = str(result.get(key) or "0").strip()
        if raw and raw not in ("0", "null", "false"):
            out.append((key, label, weight))
    out.sort(key=lambda x: -x[2])
    return out


async def run_address_risk(
    addr: str, query_type: str = "eth_address", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    address = (addr or "").strip()
    if not address:
        return [], [], ["address_risk: empty address"]

    if not EVM_RE.match(address):
        # Refuse rather than ask: see the module docstring. The API would
        # answer 200/all-clear for this and the analyst would read it as a
        # clean bill of health.
        return [], [], [
            f"{NOTE_PREFIX}address_risk covers EVM addresses (0x…) only. "
            "GoPlus answers for other chains with an all-clear that means "
            "'not indexed', not 'clean', so this address was not sent. For "
            "Bitcoin use sanctions_screen (OFAC designates 252 BTC wallets) "
            "or ransomlook_crypto."]

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True,
            headers={"User-Agent": "OOF/1.0"},
        ) as client:
            r = await client.get(f"{API}/{address}", params={"chain_id": CHAIN_ID})
        if r.status_code == 429:
            return [], [], ["address_risk: GoPlus rate limit reached (the "
                            "keyless tier is throttled) — try again shortly."]
        r.raise_for_status()
        body = r.json() or {}
    except httpx.HTTPError as e:
        return [], [], [f"address_risk: GoPlus unreachable: {type(e).__name__}"]
    except ValueError:
        return [], [], ["address_risk: GoPlus returned a non-JSON body."]

    if str(body.get("code")) != "1":
        return [], [], [f"address_risk: GoPlus said "
                        f"'{body.get('message') or 'unknown error'}'."]

    result = body.get("result") or {}
    raised = _raised(result)
    sources = [s for s in str(result.get("data_source") or "").split(",") if s]

    if not raised:
        return [], [], [
            f"{NOTE_PREFIX}address_risk: GoPlus raised no flag for this "
            "address. That means it is not in their malicious-address "
            "dataset (SlowMist, BlockSec, OFAC, Chainabuse) — it is not a "
            "statement that the address is clean."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    root = f"{query_type}:{address}"

    findings.append(Finding(
        entity_type=query_type,
        platform="goplus",
        label=address,
        url=f"https://gopluslabs.io/address-security/{CHAIN_ID}/{address}",
        # High: these are dataset memberships, not a model's opinion. What
        # each membership MEANS still varies, which is why the flags travel
        # individually instead of collapsing into one score.
        confidence=0.85,
        data={
            "risk_flags": [k for k, _, _ in raised],
            "risk_labels": [lbl for _, lbl, _ in raised],
            "sanctioned": "sanctioned" in {k for k, _, _ in raised},
            "is_contract": str(result.get("contract_address") or "0") == "1",
            "data_source": sources,
            "source": "goplus",
            "evidence": "GoPlus address_security, aggregating "
                        + (", ".join(sources) if sources else "its own dataset"),
        },
    ))

    # One node per raised flag, so two addresses flagged as `mixer` meet on
    # the same node instead of each carrying a private list nobody can join.
    for key, label, _ in raised:
        findings.append(Finding(
            entity_type="risk_flag", platform="goplus", label=label,
            confidence=0.8,
            data={"flag": key, "source": "goplus",
                  "data_source": sources},
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"risk_flag:{label}",
            relation="flagged_as", confidence=0.8,
            data={"source": "goplus", "flag": key},
        ))

    notes: list[str] = []
    if "sanctioned" in {k for k, _, _ in raised}:
        notes.append(f"{NOTE_PREFIX}address_risk: GoPlus reports this address as "
                     "sanctioned. Confirm against the issuing authority with "
                     "sanctions_screen before citing it — an aggregator's flag "
                     "is a lead, the SDN entry is the evidence.")
    return findings, edges, notes
