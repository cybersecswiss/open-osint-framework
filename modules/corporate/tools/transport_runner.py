"""Vessels and aircraft — the capability class the framework did not have.

## Why this matters more than the tool count suggests

Every other selector in the framework keys off a technical artefact (a
domain, an address, a handle) or a legal person (a company, a human). A
sanctions-evasion case very often turns on neither: it turns on a **ship**.
Cargo moves, ownership is layered through shells, and the vessel is the one
thing that cannot be re-registered out of existence — it keeps its IMO
number for life, across every change of name, flag and owner.

Without these tools, an investigator holding an IMO number would have
nowhere to type it.

## Why this needed no new source and no new key

`sanctions_runner` has been downloading the OFAC SDN list every six hours
since the module was written. Measured on that same file: **1540 vessels and
342 aircraft**, with `SDN_Type` naming them outright, six vessel-specific
columns (call sign, type, tonnage, GRT, flag, owner) and the IMO number in
the remarks — present in 1525 of 1540.

So these two tools rate Admiralty **A**: the statement comes from the
issuing authority, not from an aggregator, and it can be cited as "OFAC SDN,
programme UKR, retrieved <date>".

## What they deliberately are not

They are not a vessel-tracking or flight-tracking capability. Live position
needs a paid feed (MarineTraffic, VesselFinder, ADS-B Exchange) and belongs
in a key-gated tool alongside `wallet_attribution`. These answer one
question completely and honestly: **is this ship or this aircraft
designated, and what does the designating authority say about it.**

## The check digit is not a nicety

An IMO number carries one, and a mistyped IMO answers "not designated" —
which looks exactly like a clean result and is the single worst thing a
sanctions check can get wrong. A query that fails the check is reported as
such instead of being screened.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

# The MODULE, not the names. `_parse_ofac` REASSIGNS `_vessel_index` and
# `_aircraft_index` when it builds them, so a `from … import _vessel_index`
# would bind the empty dict that existed at import time and never see the
# real one — a lookup that always returns "not designated", which is the
# worst possible way for this to fail.
from tools import sanctions_runner as sr
from tools.sanctions_runner import OFAC_WEB, _load, _norm, imo_check_digit_ok

log = logging.getLogger("corporate.transport")

_IMO_INPUT = re.compile(r"^\s*(?:IMO[\s:]*)?([0-9]{7})\s*$", re.I)
_MMSI_INPUT = re.compile(r"^\s*(?:MMSI[\s:]*)?([0-9]{9})\s*$", re.I)
# A registration is letters, digits and hyphens: HB-JHA, EP-GOL, N123AB,
# RA-82042. Deliberately loose — national schemes differ, and a pattern
# tight enough to be "correct" would reject the next country.
_TAIL_INPUT = re.compile(r"^\s*([A-Z0-9]{1,3}-?[A-Z0-9]{1,6})\s*$", re.I)


def _prov(rec: dict[str, Any]) -> dict[str, Any]:
    """The fields that let a finding be cited rather than merely believed."""
    return {
        "list": rec.get("list") or "OFAC SDN",
        "programme": rec.get("programme") or "",
        "reference": rec.get("reference") or "",
    }


async def _ensure_index(client: httpx.AsyncClient) -> list[str]:
    """The indexes are filled as a side effect of loading the lists."""
    _, errors = await _load(client)
    return errors


# ── vessels ─────────────────────────────────────────────────────────

async def run_vessel(query: str, options: dict | None = None,
                     job_id: str = "adhoc",
                     query_type: str = "vessel") -> tuple[list, list, list]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    term = (query or "").strip()
    if not term:
        return findings, edges, ["empty query"]

    imo_m = _IMO_INPUT.match(term)
    mmsi_m = _MMSI_INPUT.match(term)
    imo = imo_m.group(1) if imo_m else ""
    mmsi = mmsi_m.group(1) if mmsi_m else ""

    if imo and not imo_check_digit_ok(imo):
        # Refuse rather than answer. "Not designated" for a typo is the
        # dangerous answer, and it is indistinguishable from a real one.
        return findings, edges, [
            f"IMO {imo} fails its check digit — this is not a valid IMO "
            f"number, so no screening was performed. Verify the number "
            f"before concluding anything."
        ]

    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        errors.extend(await _ensure_index(client))

    keys = [k for k in (imo, mmsi, term.lower(), _norm(term)) if k]
    seen: set[str] = set()
    hits: list[dict] = []
    for key in keys:
        for rec in sr._vessel_index.get(key, []):
            ident = f"{rec.get('reference')}|{rec.get('name')}"
            if ident in seen:
                continue
            seen.add(ident)
            hits.append(rec)

    if not hits:
        errors.append(
            NOTE_PREFIX + f"'{term}' is not on the OFAC SDN vessel list "
            f"({len(sr._vessel_index):,} identifiers indexed). That is a "
            f"statement about this one list, not about the vessel."
        )
        return findings, edges, errors

    for rec in hits:
        name = rec.get("name") or term
        data = {
            **_prov(rec),
            "imo": rec.get("imo") or "",
            "mmsi": rec.get("mmsi") or "",
            "call_sign": rec.get("call_sign") or "",
            "vessel_type": rec.get("vessel_type") or "",
            "tonnage": rec.get("tonnage") or "",
            "grt": rec.get("grt") or "",
            "flag": rec.get("flag") or "",
            "sanctioned": True,
        }
        findings.append(Finding(
            entity_type="vessel", label=name, url=OFAC_WEB,
            confidence=0.95, data={k: v for k, v in data.items() if v},
        ))
        edges.append(EdgeResult(
            from_entity=f"vessel:{term}", to_entity=f"vessel:{name}",
            relation="designated_as",
        ))

        # The flag state is a jurisdiction, and re-flagging is the classic
        # evasion move — so it is a node, not a footnote.
        if rec.get("flag"):
            findings.append(Finding(
                entity_type="location", label=rec["flag"],
                confidence=0.9, data={"role": "flag state", "vessel": name},
            ))
            edges.append(EdgeResult(
                from_entity=f"vessel:{name}", to_entity=f"location:{rec['flag']}",
                relation="flagged_in",
            ))

        # The registered owner is the thread back into the company graph,
        # where zefix/shab/gleif can pick it up.
        if rec.get("owner"):
            findings.append(Finding(
                entity_type="organization", label=rec["owner"],
                confidence=0.9, data={"role": "registered owner", "vessel": name},
            ))
            edges.append(EdgeResult(
                from_entity=f"vessel:{name}",
                to_entity=f"organization:{rec['owner']}",
                relation="owned_by",
            ))

        if rec.get("imo"):
            findings.append(Finding(
                entity_type="imo_number", label=rec["imo"],
                confidence=0.98, data={"vessel": name},
            ))
            edges.append(EdgeResult(
                from_entity=f"vessel:{name}", to_entity=f"imo_number:{rec['imo']}",
                relation="identified_by",
            ))

    return findings, edges, errors


# ── aircraft ────────────────────────────────────────────────────────

async def run_aircraft(query: str, options: dict | None = None,
                       job_id: str = "adhoc",
                       query_type: str = "aircraft") -> tuple[list, list, list]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    term = (query or "").strip()
    if not term:
        return findings, edges, ["empty query"]

    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        errors.extend(await _ensure_index(client))

    # A registration may be written with or without the hyphen.
    variants = {term.lower(), term.lower().replace("-", ""), _norm(term)}
    if "-" not in term and len(term) > 2:
        variants.add(f"{term[:2].lower()}-{term[2:].lower()}")

    seen: set[str] = set()
    hits: list[dict] = []
    for key in filter(None, variants):
        for rec in sr._aircraft_index.get(key, []):
            ident = f"{rec.get('reference')}|{rec.get('name')}"
            if ident in seen:
                continue
            seen.add(ident)
            hits.append(rec)

    if not hits:
        errors.append(
            NOTE_PREFIX + f"'{term}' is not on the OFAC SDN aircraft list "
            f"({len(sr._aircraft_index):,} identifiers indexed). That is a "
            f"statement about this one list, not about the aircraft."
        )
        return findings, edges, errors

    for rec in hits:
        tail = rec.get("tail") or rec.get("name") or term
        data = {
            **_prov(rec),
            "tail_number": tail,
            "model": rec.get("model") or "",
            "operator": rec.get("operator") or "",
            "msn": rec.get("msn") or "",
            "construction_number": rec.get("construction_number") or "",
            "sanctioned": True,
        }
        findings.append(Finding(
            entity_type="aircraft", label=tail, url=OFAC_WEB,
            confidence=0.95, data={k: v for k, v in data.items() if v},
        ))
        edges.append(EdgeResult(
            from_entity=f"aircraft:{term}", to_entity=f"aircraft:{tail}",
            relation="designated_as",
        ))

        # The operator is the organisation actually flying it, which is
        # rarely the owner and is usually the more useful thread.
        if rec.get("operator"):
            findings.append(Finding(
                entity_type="organization", label=rec["operator"],
                confidence=0.9, data={"role": "aircraft operator", "aircraft": tail},
            ))
            edges.append(EdgeResult(
                from_entity=f"aircraft:{tail}",
                to_entity=f"organization:{rec['operator']}",
                relation="operated_by",
            ))

        # The MSN survives a re-registration; the tail number does not.
        # For an aircraft that changes marks to shed a designation, it is
        # the identifier that still holds.
        if rec.get("msn"):
            findings.append(Finding(
                entity_type="aircraft_serial", label=rec["msn"],
                confidence=0.95, data={"aircraft": tail, "kind": "MSN"},
            ))
            edges.append(EdgeResult(
                from_entity=f"aircraft:{tail}",
                to_entity=f"aircraft_serial:{rec['msn']}",
                relation="identified_by",
            ))

    return findings, edges, errors
