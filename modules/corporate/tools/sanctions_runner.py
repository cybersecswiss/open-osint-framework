"""Sanctions screening against the primary lists — EU FSF + OFAC SDN (keyless).

The framework already has `opensanctions`, which is better data — it
consolidates dozens of lists into one graph. It is also **key-gated**, and on
an instance without that key the entire compliance capability is dark. This
tool is the keyless floor underneath it: the two lists that matter most for
sanctions screening in Switzerland, fetched from the issuing authority itself.

    EU  Financial Sanctions Files (FSF)   ~42 000 name rows, `;`-separated
    US  OFAC Specially Designated Nationals  ~19 000 rows, headerless CSV

Being the primary source has a specific value here: a hit can be cited as
"EU FSF, programme UKR, retrieved <date>" rather than as "an aggregator said
so". Findings therefore rate Admiralty **A**.

**Matching is deliberately conservative.** Sanctions matching is where false
positives do real damage to real people, so this does not fuzzy-match: it
compares normalised strings and accepts an exact match or a full-token
containment — every word of the query must appear as a *whole word* in the
listed name, in any order. Order-independence is not a loosening: the EU file
writes "Vladimir Vladimirovich PUTIN" and OFAC writes "PUTIN, Vladimir
Vladimirovich", so requiring the typed order meant one of the two lists fell
away depending on how the name was typed — a false "no hits", which is the
one failure a sanctions check must never produce.
"Ivan Petrov" will not match "Ivanov, Petr". Aliases are covered because both
lists publish them as their own rows — the EU file is one row *per alias*,
which is why a single entity produces several hits and they are merged here.

Both files are cached in-process for six hours. They change daily at most,
and re-downloading 30 MB for every tool in a module run would be absurd.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import time
import unicodedata
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

EU_FSF = ("https://webgate.ec.europa.eu/fsd/fsf/public/files/"
          "csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw")  # gitleaks:allow — public EU FSF token
OFAC_SDN = "https://www.treasury.gov/ofac/downloads/sdn.csv"
EU_WEB = "https://www.sanctionsmap.eu/"
OFAC_WEB = "https://sanctionssearch.ofac.treas.gov/"

USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 90
CACHE_TTL = 6 * 3600
MAX_HITS = 25

log = logging.getLogger("module-corporate.sanctions")

# name (normalised) -> list of records
_index: dict[str, list[dict[str, Any]]] = {}
_indexed_at: float = 0.0
_index_meta: dict[str, Any] = {}

# --- crypto addresses -----------------------------------------------------
#
# OFAC publishes designated wallet addresses inside the SDN remarks column,
# as `Digital Currency Address - XBT 1Kuf2Rd8…` with further ones prefixed
# `alt.`. One snapshot: 452 addresses over 8 chains — 252 XBT, 72 ETH,
# 64 TRX, 42 USDT, 8 LTC, 6 XMR, 5 DASH, 3 ZEC.
#
# This is worth having even though the framework has crypto risk tools:
# a sanctions hit is a statement by an issuing authority, citable as "OFAC
# SDN, programme CYBER2, retrieved <date>", where a vendor's risk score is an
# opinion. It also reaches chains no scoring API here covers — Monero above
# all, where nothing else in this framework can say anything at all.
#
# ⚠️ **EU FSF does NOT publish addresses in a parseable form** (checked
# against the live file). A miss from this tool therefore means "not on the
# OFAC SDN crypto list", never "not sanctioned" — and the note says so,
# because for a sanctions check a falsely reassuring negative is the one
# outcome that must not happen quietly.
_ADDR_RE = re.compile(
    r"Digital Currency Address\s*-\s*([A-Z0-9]{2,6})\s+([A-Za-z0-9]{16,120})")

# Chain code in the SDN remark -> the entity type the graph already uses, so
# a designated address collapses onto the node the crypto module produced
# rather than sitting next to it. Chains with no canonical type here keep a
# generic node: better a typed-as-generic hit than no hit.
_CHAIN_TYPE = {"XBT": "btc_address", "ETH": "eth_address"}

# address (lowercased) -> list of records
_addr_index: dict[str, list[dict[str, Any]]] = {}

# Vessels and aircraft, built in the same pass as the address index and for
# the same reason: the file is 5.7 MB and parsing it three times for three
# indexes would be silly.
#
# ⚠️ These two categories are easy to overlook in this file. One snapshot of
# the SDN list contains **1540 vessels and 342 aircraft** — the central
# selectors for a sanctions-evasion case, in a file the tool already
# downloads every six hours. `SDN_Type` names them outright, and columns 5–10 are vessel-specific
# (call sign, type, tonnage, GRT, flag, owner) with the IMO number in the
# remarks (present in 1525 of 1540). For aircraft the NAME is the tail
# number, with model, operator and serial numbers in the remarks.
_vessel_index: dict[str, list[dict[str, Any]]] = {}
_aircraft_index: dict[str, list[dict[str, Any]]] = {}

# Identifiers OFAC writes into the remarks column, in its own prose.
_IMO_RE = re.compile(r"\bIMO\s*([0-9]{7})\b", re.I)
_MMSI_RE = re.compile(r"\bMMSI\s*([0-9]{9})\b", re.I)
_TAIL_RE = re.compile(r"Aircraft Tail Number\s*([A-Z0-9][A-Z0-9\-]{2,9})", re.I)
_MSN_RE = re.compile(r"Serial Number \(MSN\)\s*([A-Za-z0-9\-]+)", re.I)
_CONSTR_RE = re.compile(r"Aircraft Construction Number[^0-9]*([0-9]{2,10})", re.I)
_MODEL_RE = re.compile(r"Aircraft Model\s*([^;]+)", re.I)
_OPERATOR_RE = re.compile(r"Aircraft Operator\s*([^;]+)", re.I)


def _clean(v: str | None) -> str:
    """OFAC writes `-0-` for "no value". Left as-is it turns into a field
    that looks populated and reads as nonsense in a case file."""
    v = (v or "").strip()
    return "" if v in ("-0-", "-0- ", "") else v


def imo_check_digit_ok(imo: str) -> bool:
    """An IMO number carries a check digit: the first six digits weighted
    7,6,5,4,3,2, summed, and the last digit of that sum must be the seventh.

    Worth validating before answering. A mistyped IMO produces "not on the
    sanctions list", which is the one answer a sanctions check must never
    give wrongly — and it looks exactly like a clean result.
    """
    digits = re.sub(r"\D", "", imo or "")
    if len(digits) != 7:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:6], range(7, 1, -1)))
    return total % 10 == int(digits[6])

_WS_RE = re.compile(r"[^\w\s]+", re.UNICODE)

# Both lists code the subject type as a letter; spell it out so a reader does
# not have to know that "E" means entity and "P" means a natural person.
_SUBJECT_TYPES = {
    "e": "entity", "p": "person", "enterprise": "entity",
    "individual": "person", "-0-": "",
}


def _norm(s: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.
    Transliteration is NOT attempted — guessing that a Cyrillic name equals
    its Latin spelling is the kind of inference that belongs to a human."""
    s = unicodedata.normalize("NFKD", (s or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _WS_RE.sub(" ", s).casefold()
    return " ".join(s.split())


def _parse_eu(text: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        name = (row.get("NameAlias_WholeName") or "").strip()
        if not name:
            first = (row.get("NameAlias_FirstName") or "").strip()
            last = (row.get("NameAlias_LastName") or "").strip()
            name = f"{first} {last}".strip()
        if not name:
            continue
        rec = {
            "list": "EU FSF",
            "name": name,
            "programme": (row.get("NameAlias_Regulation_Programme")
                          or row.get("Entity_Regulation_Programme") or "").strip(),
            "type": _SUBJECT_TYPES.get((row.get("Entity_SubjectType") or "").strip().lower(),
                                       (row.get("Entity_SubjectType") or "").strip()),
            "birth_date": (row.get("BirthDate_BirthDate") or "").strip(),
            "country": (row.get("Address_CountryDescription")
                        or row.get("Address_CountryIso2Code") or "").strip(),
            "reference": (row.get("Entity_EU_ReferenceNumber") or "").strip(),
            "url": EU_WEB,
        }
        out.setdefault(_norm(name), []).append(rec)
    return out


def _parse_ofac(text: str) -> dict[str, list[dict]]:
    """SDN is headerless: uid, name, type, programme, title, …

    Also fills the module-level `_addr_index` from the remarks column — see
    the `_ADDR_RE` note. Done in the same pass because the file is 5 MB and
    parsing it twice for two indexes would be silly.
    """
    global _addr_index, _vessel_index, _aircraft_index
    addrs: dict[str, list[dict]] = {}
    vessels: dict[str, list[dict]] = {}
    aircraft: dict[str, list[dict]] = {}
    out: dict[str, list[dict]] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 4:
            continue
        name = (row[1] or "").strip()
        if not name or name == "-0-":
            continue
        # OFAC packs several programmes into one field as "[A] [B]".
        programme = (row[3] or "").strip().replace("-0-", "")
        programme = " ".join(re.findall(r"\[?([A-Za-z0-9_\-]+)\]?", programme))
        rec = {
            "list": "OFAC SDN",
            "name": name,
            "programme": programme,
            "type": _SUBJECT_TYPES.get((row[2] or "").strip().lower(),
                                       (row[2] or "").strip().replace("-0-", "")),
            "birth_date": "",
            "country": "",
            "reference": (row[0] or "").strip(),
            "url": OFAC_WEB,
        }
        out.setdefault(_norm(name), []).append(rec)

        # Designated wallets live in the remarks column, several per entry.
        remarks = row[11] if len(row) > 11 else ""
        for chain, addr in _ADDR_RE.findall(remarks or ""):
            addrs.setdefault(addr.lower(), []).append({**rec, "chain": chain,
                                                       "address": addr})

        sdn_type = (row[2] or "").strip().lower()
        if sdn_type == "vessel":
            imo_m = _IMO_RE.search(remarks or "")
            mmsi_m = _MMSI_RE.search(remarks or "")
            imo = imo_m.group(1) if imo_m else ""
            v = {
                **rec,
                "imo": imo,
                "mmsi": mmsi_m.group(1) if mmsi_m else "",
                "call_sign": _clean(row[5] if len(row) > 5 else ""),
                "vessel_type": _clean(row[6] if len(row) > 6 else ""),
                "tonnage": _clean(row[7] if len(row) > 7 else ""),
                "grt": _clean(row[8] if len(row) > 8 else ""),
                "flag": _clean(row[9] if len(row) > 9 else ""),
                "owner": _clean(row[10] if len(row) > 10 else ""),
                "remarks": _clean(remarks),
            }
            # Indexed under every identifier it carries, so an investigator
            # can start from whichever one they have.
            for key in filter(None, (v["imo"], v["mmsi"],
                                     v["call_sign"].lower() or None, _norm(name))):
                vessels.setdefault(str(key), []).append(v)
        elif sdn_type == "aircraft":
            tail_m = _TAIL_RE.search(remarks or "")
            msn_m = _MSN_RE.search(remarks or "")
            constr_m = _CONSTR_RE.search(remarks or "")
            model_m = _MODEL_RE.search(remarks or "")
            op_m = _OPERATOR_RE.search(remarks or "")
            # For aircraft the SDN NAME is the registration — "EP-GOL". The
            # explicit "Aircraft Tail Number" field appears in fewer than
            # half the rows (164 of 342, measured), so the name is the
            # primary key and the field is a second one when present.
            a = {
                **rec,
                "tail": (tail_m.group(1).upper() if tail_m else name.upper()),
                "msn": msn_m.group(1) if msn_m else "",
                "construction_number": constr_m.group(1) if constr_m else "",
                "model": (model_m.group(1).strip() if model_m else ""),
                "operator": (op_m.group(1).strip() if op_m else ""),
                "remarks": _clean(remarks),
            }
            for key in filter(None, (a["tail"].lower(), a["msn"].lower() or None,
                                     a["construction_number"] or None, _norm(name))):
                aircraft.setdefault(str(key), []).append(a)

    _addr_index = addrs
    _vessel_index = vessels
    _aircraft_index = aircraft
    return out


async def _load(client: httpx.AsyncClient) -> tuple[dict, list[str]]:
    global _index, _indexed_at, _index_meta
    if _index and (time.time() - _indexed_at) < CACHE_TTL:
        return _index, []

    notes: list[str] = []
    merged: dict[str, list[dict]] = {}
    loaded: list[str] = []

    async def grab(url: str, parser, label: str):
        try:
            r = await client.get(url)
            r.raise_for_status()
            return label, parser(r.text)
        except (httpx.HTTPError, ValueError, csv.Error) as e:
            log.warning("sanctions: %s unavailable: %s", label, e)
            return label, None

    results = await asyncio.gather(
        grab(EU_FSF, _parse_eu, "EU FSF"),
        grab(OFAC_SDN, _parse_ofac, "OFAC SDN"),
    )
    for label, part in results:
        if part is None:
            notes.append(f"{NOTE_PREFIX}sanctions_screen: {label} could not be "
                         "fetched — this run does not cover it.")
            continue
        loaded.append(label)
        for key, recs in part.items():
            merged.setdefault(key, []).extend(recs)

    if not merged:
        # Never replace a usable index with an empty one: reporting "no
        # sanctions hit" because a download failed is the worst possible
        # error for this particular tool.
        if _index:
            notes.append(f"{NOTE_PREFIX}sanctions_screen: both lists unreachable, "
                         "using the cached copy from the last successful fetch.")
            return _index, notes
        notes.append("sanctions_screen: no sanctions list could be fetched — "
                     "this is NOT a negative result.")
        return {}, notes

    _index = merged
    _indexed_at = time.time()
    _index_meta = {"names": len(merged), "lists": loaded}
    return _index, notes


def _match(index: dict[str, list[dict]], term: str) -> list[dict]:
    key = _norm(term)
    if not key:
        return []
    hits = list(index.get(key, []))
    if hits:
        return hits
    # Full-token containment, ORDER-INDEPENDENT: every word of the query must
    # appear as a whole word in the listed name, but not necessarily in the
    # sequence it was typed. The EU file writes "Vladimir Vladimirovich PUTIN",
    # OFAC writes "PUTIN, Vladimir Vladimirovich" — requiring the typed order
    # silently dropped one of the two lists depending on how the analyst
    # happened to type the name, which is the worst possible failure for a
    # sanctions check. Still deliberately not fuzzy: whole words only, so
    # "Ivan Petrov" continues not to match "Ivanov, Petr".
    tokens = key.split()
    if len(tokens) < 1 or len(key) < 4:
        return []
    # Rarest-looking token first: `all()` short-circuits, and the longest
    # token is the one most likely to fail, so this keeps the scan cheap.
    patterns = [re.compile(r"\b" + re.escape(t) + r"\b")
                for t in sorted(tokens, key=len, reverse=True)]
    for name_key, recs in index.items():
        if all(p.search(name_key) for p in patterns):
            hits.extend(recs)
            if len(hits) >= MAX_HITS:
                break
    return hits


def _screen_address(
    addr: str, query_type: str, errors: list[str],
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    """Is this wallet designated by OFAC?

    Exact match, lowercased, and nothing else. Sanctions screening of an
    address is the one place where fuzziness would be indefensible: a wallet
    is a machine identifier, so a near-match is a different wallet belonging
    to a different person. There is no transliteration problem to compensate
    for here, which is exactly why the name path needs whole-word logic and
    this path must not have any.
    """
    hits = _addr_index.get(addr.strip().lower(), [])
    if not hits:
        errors.append(
            f"{NOTE_PREFIX}sanctions_screen: this address is not among the "
            f"{len(_addr_index):,} wallets OFAC designates on the SDN list. "
            "EU FSF does not publish addresses, so this is NOT a statement "
            "that the address is unsanctioned anywhere.")
        return [], [], errors

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    root = f"{query_type}:{addr}"
    seen_lists: set[str] = set()

    for h in hits[:MAX_HITS]:
        name = h["name"]
        # `rec["type"]` has already been through _SUBJECT_TYPES, so the raw
        # SDN word "individual" never survives to here — comparing against it
        # filed every designated person as an organisation.
        subject_type = "person" if h.get("type") == "person" else "organization"
        findings.append(Finding(
            entity_type=subject_type,
            label=name,
            url=h.get("url"),
            # A designated wallet is an identifier the authority itself
            # published against a named party. There is no inference step.
            confidence=0.95,
            data={
                "sanctioned": True,
                "sanction_lists": [h["list"]],
                "sanction_programmes": [p for p in [h.get("programme")] if p],
                "subject_type": h.get("type"),
                "list_reference": h.get("reference"),
                "matched_address": h.get("address"),
                "chain": h.get("chain"),
                "matched_query": addr,
                "source": "sanctions_screen",
            },
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"{subject_type}:{name}",
            relation="designated_wallet_of", confidence=0.95,
            data={"list": h["list"], "chain": h.get("chain"),
                  "programme": h.get("programme")},
        ))
        if h["list"] not in seen_lists:
            seen_lists.add(h["list"])
            findings.append(Finding(
                entity_type="sanction_list", label=h["list"], url=h.get("url"),
                confidence=0.95, data={"source": "sanctions_screen"},
            ))
        edges.append(EdgeResult(
            from_entity=f"{subject_type}:{name}",
            to_entity=f"sanction_list:{h['list']}",
            relation="listed_on", confidence=0.95,
        ))

    if len(hits) > MAX_HITS:
        errors.append(f"{NOTE_PREFIX}sanctions_screen: {len(hits)} designations "
                      f"reference this address, {MAX_HITS} returned.")

    # The lookup is chain-agnostic on purpose: OFAC designates addresses on
    # eight chains and the framework has query types for two, so a Monero or
    # TRON wallet is only checkable at all if it can be pasted into one of
    # them. That is worth having — nothing else here says anything about
    # Monero. But it does mean the ROOT node carries the type the analyst
    # picked rather than the real chain, so say it out loud instead of
    # leaving a mislabelled node in an evidentiary graph.
    chains = {h.get("chain") for h in hits[:MAX_HITS]} - {None, ""}
    expected = {"btc_address": "XBT", "eth_address": "ETH"}[query_type]
    if chains and expected not in chains:
        errors.append(
            f"{NOTE_PREFIX}sanctions_screen: this is a "
            f"{'/'.join(sorted(chains))} address, entered as "
            f"{query_type.replace('_address', '').upper()}. The designation "
            "is real; only the node's type follows what was typed.")
    return findings, edges, errors


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["sanctions_screen: empty search term"]

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        index, errors = await _load(client)

    if not index:
        return [], [], errors

    if query_type in ("btc_address", "eth_address"):
        return _screen_address(term, query_type, errors)

    hits = _match(index, term)
    if not hits:
        errors.append(f"{NOTE_PREFIX}sanctions_screen: '{term}' is not on the "
                      f"{', '.join(_index_meta.get('lists', []))} "
                      f"({_index_meta.get('names', 0):,} listed names checked). "
                      "A different spelling or transliteration may still be listed.")
        return [], [], errors

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    capped = hits[:MAX_HITS]

    # One entity typically appears several times (one row per alias); merge
    # into a single finding per listed name so the graph is not flooded.
    by_name: dict[str, dict] = {}
    for h in capped:
        cur = by_name.setdefault(h["name"], {**h, "programmes": set(), "lists": set()})
        if h.get("programme"):
            cur["programmes"].add(h["programme"])
        cur["lists"].add(h["list"])

    is_person = query_type == "person_name"
    root_type = "person" if is_person else "organization"

    for name, h in by_name.items():
        findings.append(Finding(
            entity_type=root_type,
            label=name,
            url=h.get("url"),
            confidence=0.95,
            data={
                "sanctioned": True,
                "sanction_lists": sorted(h["lists"]),
                "sanction_programmes": sorted(p for p in h["programmes"] if p),
                "subject_type": h.get("type"),
                "birth_date": h.get("birth_date"),
                "country": h.get("country"),
                "list_reference": h.get("reference"),
                "matched_query": term,
                "source": "sanctions_screen",
            },
        ))
        for lst in sorted(h["lists"]):
            findings.append(Finding(
                entity_type="sanction_list", label=lst, url=h.get("url"),
                confidence=0.95, data={"source": "sanctions_screen"},
            ))
            edges.append(EdgeResult(
                from_entity=f"{root_type}:{name}",
                to_entity=f"sanction_list:{lst}",
                relation="listed_on",
                confidence=0.95,
                data={"programmes": sorted(p for p in h["programmes"] if p)},
            ))
        if _norm(name) != _norm(term):
            edges.append(EdgeResult(
                from_entity=f"{query_type}:{term}", to_entity=f"{root_type}:{name}",
                relation="matches_listed_name", confidence=0.8,
            ))

    if len(hits) > MAX_HITS:
        errors.append(f"{NOTE_PREFIX}sanctions_screen: {len(hits)} list rows matched, "
                      f"{MAX_HITS} returned.")
    errors.append(f"{NOTE_PREFIX}sanctions_screen: matched by exact/whole-word "
                  "comparison against the official lists, in any word order — no "
                  "fuzzy matching, so a differently transliterated name would not "
                  "appear here.")
    return findings, edges, errors
