"""ZEFIX — the Swiss central business name index (key required).

`shab_registry` reads PUBLICATIONS: the events in a company's life, as they
were printed. ZEFIX holds the STATE: what the 26 cantonal commercial
registers say about the company right now, aggregated federally. The two
answer different questions and the framework needed both —
"who signed for this company in 2022" is a SHAB question, "what is this
company today, and what else hangs off it" is a ZEFIX one.

What this adds beyond SHAB:

* the **corporate network** as structured data — head offices, branch
  offices, companies taken over, the company that took this one over, and
  the audit firm. SHAB has these only as prose inside a publication text.
* **purpose** (Zweck), nominal capital and currency,
* **previous names** — the single most useful field for a shell company,
* the **canton** and a clean postal address as fields rather than parsed
  out of a sentence,
* a link to the cantonal register excerpt, which is the citable document.

Authentication: HTTP **Basic**, realm `ZefixPublicREST` (measured — the
service answers 401 with `WWW-Authenticate: Basic`). The key is therefore a
`username:password` pair, not a token; that is what goes in the
`ZEFIX_API_KEY` field of the Owner console. Registration is free at
https://www.zefix.admin.ch/de/search/entity/welcome (Web-Service anmelden).

Licence: the API publishes itself as "OGD Open use. Must provide the
source." — attribution is a condition of use, so every finding carries
`register` and `source`, and they must not be stripped downstream.

⚠️  UID FORMATTING IS AN IDENTITY QUESTION, NOT COSMETICS.
ZEFIX returns the UID unformatted (`CHE105845843`); `shab_registry` emits it
formatted (`CHE-105.845.843`). `company_id` is a case-insensitive canonical
type, but "CHE105845843" and "CHE-105.845.843" are not the same string in any
casing — they would become two nodes for one company, and the corroboration
between the two registers, which is the strongest signal this module can
produce, would be lost. `_format_uid()` normalises onto SHAB's spelling.

⚠️  UNVERIFIED AGAINST A LIVE KEY.
This runner was written against the service's own published OpenAPI schema
(`/v3/api-docs`, which is readable without credentials), not against a real
response. The field names are therefore correct by specification but have
not been verified against a live response. `_expect_company()`
exists for exactly that gap: on a 200 whose body carries none of the
documented fields it reports loudly instead of returning zero findings, so
"the schema moved" cannot present itself as "this company does not exist".
Delete this notice once a run with a real key has been seen.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding, credential

BASE = "https://www.zefix.admin.ch/ZefixPublicREST/api/v1"
REGISTER_URL = "https://www.zefix.admin.ch/de/search/entity/welcome"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
MAX_COMPANIES = 10        # search hits taken forward to a detail fetch
MAX_RELATED = 25          # related companies emitted per company

# CHE-123.456.789 or CHE123456789, case-insensitive.
_UID_RE = re.compile(r"\bCHE[-\s]?(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})\b", re.I)

# CompanyFull fields that carry other companies, and the relation each one
# means. Declared as data rather than as branching code so adding one is a
# line — and so the relation names stay in one place, readable.
_RELATIONS: tuple[tuple[str, str], ...] = (
    ("headOffices",        "head_office_of"),
    ("furtherHeadOffices", "head_office_of"),
    ("branchOffices",      "branch_office"),
    ("hasTakenOver",       "took_over"),
    ("wasTakenOverBy",     "taken_over_by"),
    ("auditCompanies",     "audited_by"),
)

log = logging.getLogger("module-corporate.zefix")


def _format_uid(raw: Any) -> str:
    """Normalise a UID onto SHAB's spelling — see the module docstring."""
    m = _UID_RE.search(str(raw or ""))
    if not m:
        return str(raw or "").strip()
    return f"CHE-{m.group(1)}.{m.group(2)}.{m.group(3)}"


def looks_like_uid(term: str) -> bool:
    return bool(_UID_RE.search(term or ""))


def _auth_header(key: str) -> dict[str, str]:
    """Basic auth from a `user:password` value.

    A value without a colon is passed through as-is rather than rejected: if
    the service ever issues single-token credentials, an operator pasting one
    should get the service's own answer, not ours.
    """
    token = base64.b64encode(key.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _text(value: Any) -> str:
    """ZEFIX returns some labels as {de,fr,it,en} objects (DFIEString)."""
    if isinstance(value, dict):
        for lang in ("de", "fr", "it", "en"):
            val = value.get(lang)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
    return str(value or "").strip()


def _address(addr: Any) -> str:
    if not isinstance(addr, dict):
        return ""
    parts = [
        " ".join(x for x in (_text(addr.get("street")),
                             _text(addr.get("houseNumber"))) if x),
        " ".join(x for x in (_text(addr.get("swissZipCode")),
                             _text(addr.get("city"))) if x),
    ]
    return ", ".join(p for p in parts if p)


def _expect_company(payload: Any) -> bool:
    """Does this body look like the documented company shape at all?

    The guard for the "unverified schema" caveat in the module docstring: a
    200 with an unrecognisable body must be reported as such. Returning an
    empty finding list would render as "no such company", which is a
    different and much more damaging statement.
    """
    items = payload if isinstance(payload, list) else [payload]
    return any(isinstance(i, dict) and ("name" in i or "uid" in i) for i in items)


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    r = await client.get(f"{BASE}{path}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


async def _search(client: httpx.AsyncClient, name: str) -> list[dict[str, Any]]:
    # activeOnly is deliberately NOT set: a deleted company is often the
    # point of the search (a shell wound up after the money moved), and the
    # status field says which it is.
    r = await client.post(f"{BASE}/company/search", json={"name": name})
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def _company_findings(company: dict[str, Any], query_type: str, term: str,
                      ) -> tuple[list[Finding], list[EdgeResult]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    name = _text(company.get("name"))
    if not name:
        return [], []
    uid = _format_uid(company.get("uid"))
    seat = _text(company.get("legalSeat"))
    canton = _text(company.get("canton"))
    status = _text(company.get("status"))
    address = _address(company.get("address"))
    detail_url = (_text(company.get("zefixDetailWeb"))
                  or _text(company.get("cantonalExcerptWeb")) or None)
    legal_form = ""
    lf = company.get("legalForm")
    if isinstance(lf, dict):
        legal_form = _text(lf.get("name") or lf.get("shortName"))

    old_names = [
        _text(o.get("name")) for o in (company.get("oldNames") or [])
        if isinstance(o, dict) and _text(o.get("name"))
    ]

    findings.append(Finding(
        entity_type="organization",
        label=name,
        url=detail_url,
        confidence=0.95,
        data={
            "uid": uid or None,
            "chid": _text(company.get("chid")) or None,
            "ehraid": company.get("ehraid"),
            "legal_form": legal_form or None,
            "status": status or None,
            "seat": seat or None,
            "canton": canton or None,
            "address": address or None,
            "purpose": _text(company.get("purpose"))[:1500] or None,
            "capital": " ".join(x for x in (_text(company.get("capitalNominal")),
                                            _text(company.get("capitalCurrency")))
                                if x) or None,
            # The field that gives a shell company away.
            "previous_names": old_names or None,
            "translations": [t for t in (company.get("translation") or []) if t] or None,
            "last_sogc_publication": _text(company.get("sogcDate")) or None,
            "deleted_on": _text(company.get("deletionDate")) or None,
            "cantonal_excerpt": _text(company.get("cantonalExcerptWeb")) or None,
            "register": "ZEFIX — central business name index (CH)",
            # Attribution is a licence condition, not decoration. See docstring.
            "attribution": "Source: ZEFIX / Federal Registry of Commerce (OGD)",
            "source": "zefix",
        },
    ))
    edges.append(EdgeResult(
        from_entity=f"{query_type}:{term}", to_entity=f"organization:{name}",
        relation="registered_as", confidence=0.9,
    ))

    if uid:
        findings.append(Finding(
            entity_type="company_id", label=uid, url=detail_url, confidence=0.95,
            data={"register": "UID (CH)", "company": name, "source": "zefix"},
        ))
        edges.append(EdgeResult(
            from_entity=f"organization:{name}", to_entity=f"company_id:{uid}",
            relation="has_identifier", confidence=0.95,
        ))

    # The seat as a location, so corporate/geo_ch can resolve it to an
    # address, a building and a parcel — the chain the two tools form.
    place = address or seat
    if place:
        findings.append(Finding(
            entity_type="location", label=place, url=detail_url, confidence=0.9,
            data={"role": "registered seat", "municipality": seat or None,
                  "canton": canton or None, "source": "zefix"},
        ))
        edges.append(EdgeResult(
            from_entity=f"organization:{name}", to_entity=f"location:{place}",
            relation="seat_at", confidence=0.9,
        ))

    # Previous names, as their own nodes. A renamed company IS the thing an
    # investigator is chasing when the name in a contract no longer exists.
    for old in old_names[:MAX_RELATED]:
        if old == name:
            continue
        findings.append(Finding(
            entity_type="organization", label=old, url=detail_url, confidence=0.9,
            data={"role": "previous name", "current_name": name,
                  "register": "ZEFIX — central business name index (CH)",
                  "source": "zefix"},
        ))
        edges.append(EdgeResult(
            from_entity=f"organization:{name}", to_entity=f"organization:{old}",
            relation="previously_named", confidence=0.9,
        ))

    # The corporate network.
    emitted = 0
    for field, relation in _RELATIONS:
        for rel in (company.get(field) or []):
            if not isinstance(rel, dict) or emitted >= MAX_RELATED:
                continue
            rel_name = _text(rel.get("name"))
            if not rel_name or rel_name == name:
                continue
            emitted += 1
            rel_uid = _format_uid(rel.get("uid"))
            findings.append(Finding(
                entity_type="organization", label=rel_name, confidence=0.9,
                data={"uid": rel_uid or None,
                      "seat": _text(rel.get("legalSeat")) or None,
                      "status": _text(rel.get("status")) or None,
                      "relation_to": name, "relation": relation,
                      "register": "ZEFIX — central business name index (CH)",
                      "source": "zefix"},
            ))
            edges.append(EdgeResult(
                from_entity=f"organization:{name}",
                to_entity=f"organization:{rel_name}",
                relation=relation, confidence=0.9,
            ))
    return findings, edges


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["zefix_registry: empty search term"]

    # MUST go through credential(): a runner reading os.environ never sees a
    # key saved in the Owner console, while the panel reports it as set.
    key = credential(options, "ZEFIX_API_KEY")
    if not key:
        return [], [], [
            "zefix_registry: no ZEFIX_API_KEY configured. ZEFIX uses HTTP "
            "Basic auth, so the value is a `username:password` pair. "
            f"Register the web service (free) at {REGISTER_URL} and save it "
            "in the Product-Owner console → Settings. Until then "
            "shab_registry still covers the commercial register, but only "
            "as published events, not as current state."
        ]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json",
               **_auth_header(key)}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                 headers=headers) as client:
        try:
            if looks_like_uid(term):
                uid = _format_uid(term).replace("-", "").replace(".", "")
                payload = await _get(client, f"/company/uid/{uid}")
                if payload is None:
                    return [], [], [f"{NOTE_PREFIX}zefix_registry: no company "
                                    f"registered under UID {_format_uid(term)}."]
                companies = payload if isinstance(payload, list) else [payload]
            else:
                shortlist = await _search(client, term)
                if not shortlist:
                    return [], [], [f"{NOTE_PREFIX}zefix_registry: no Swiss "
                                    f"company matches '{term}'."]
                if len(shortlist) > MAX_COMPANIES:
                    errors.append(f"{NOTE_PREFIX}zefix_registry: {len(shortlist)} "
                                  f"companies match '{term}'; the first "
                                  f"{MAX_COMPANIES} were read in full.")
                companies = []
                for short in shortlist[:MAX_COMPANIES]:
                    uid = _format_uid(short.get("uid")).replace("-", "").replace(".", "")
                    full = await _get(client, f"/company/uid/{uid}") if uid else None
                    if isinstance(full, list):
                        companies.extend(full)
                    elif isinstance(full, dict):
                        companies.append(full)
                    else:
                        # Detail unavailable — keep the search row rather than
                        # dropping a real company because one call failed.
                        companies.append(short)
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (401, 403):
                return [], [], [
                    f"zefix_registry: ZEFIX refused the credentials (HTTP {code}). "
                    "The value must be `username:password` for HTTP Basic auth, "
                    f"not a token. Re-check it in the Owner console; register at "
                    f"{REGISTER_URL}."]
            return [], [], [f"zefix_registry: ZEFIX returned HTTP {code}."]
        except httpx.HTTPError as e:
            return [], [], [f"zefix_registry: ZEFIX unreachable: {e}"]
        except ValueError as e:
            return [], [], [f"zefix_registry: unreadable response from ZEFIX: {e}"]

    if not _expect_company(companies):
        # See the "unverified schema" note in the module docstring. Silence
        # here would read as "this company does not exist".
        return [], [], [
            "zefix_registry: ZEFIX answered, but the response carries none of "
            "the documented company fields (`name`, `uid`). The API schema has "
            "probably changed — refusing to report this as 'not found'. "
            "Compare against https://www.zefix.admin.ch/ZefixPublicREST/v3/api-docs"]

    for company in companies:
        if not isinstance(company, dict):
            continue
        f, e = _company_findings(company, query_type, term)
        findings.extend(f)
        edges.extend(e)

    if findings:
        errors.append(f"{NOTE_PREFIX}zefix_registry: source ZEFIX / Federal "
                      f"Registry of Commerce (open government data, "
                      f"attribution required).")
    return findings, edges, errors
