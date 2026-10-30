"""Swiss commercial-register publications — SHAB / FOSC (keyless).

Every change to a Swiss company must be published in the Schweizerisches
Handelsamtsblatt: incorporation, change of purpose, change of address,
who gained or lost signing authority, and deletion. It is a primary
official record, which is why findings from here rate Admiralty **A**.

For a procurement or sanctions-evasion case this is often the only place a
foreign structure becomes concrete. Searching a foreign group's name can
return its Swiss branch with UID and address, the entry transferring
individual signing authority to a named local representative, and the later
deletion "par suite de cessation de l'exploitation".

**The search parameter is `keyword`, and this is not cosmetic.** The API
also accepts `query`, `q`, `fullText` and `searchTerm` — and silently
ignores all of them, answering with the entire corpus (2.8 million
publications) as if it had matched. A runner built on any of those would
report the newest unrelated publications as hits for every search term.

Two kinds of finding come out of one publication:

* the **company** — name, UID, legal form, seat, address, status. Structured
  fields straight out of the XML, so this is the hard result.
* the **people** — officers and signatories. These live in the free-text
  `publicationText`, in a formulaic but language-dependent phrasing
  (DE "Muster, Hans, von Zug, in Bern, Mitglied des Verwaltungsrates";
  FR "Signature individuelle a été conférée à Filonenko Ivan, de Russie, à
  Genève"; IT "Petraglio, Flavio Nino, da Breggia, a Lumino"). They are
  extracted conservatively and always carry the sentence they came from, so
  the reader can check the extraction rather than trust it.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

BASE = "https://www.shab.ch/api/v1/publications"
WEB = "https://www.shab.ch/#!/search/publications/detail/{id}"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
MAX_PUBLICATIONS = 25
MAX_DETAIL = 12          # full-text fetches per run — one HTTP call each
DETAIL_CONCURRENCY = 4

log = logging.getLogger("module-corporate.shab")

# A person as written in a register entry: 1–3 name parts (separated by a
# space OR a comma, since German entries invert to "Surname, Given"),
# then origin, then residence. Anchored on the "von/de/di" + "in/à/a"
# construction, which is what makes it specific enough to be useful — a
# bare capitalised-word pattern would match company names and cantons.
_PERSON_RE = re.compile(
    r"\b([A-ZÀ-Þ][\wÀ-ÿ'’\-]{1,}(?:\s*,?\s+[A-ZÀ-Þ][\wÀ-ÿ'’\-]{1,}){0,2}),\s+"
    r"(?:de|von|di|da|del)\s+([A-ZÀ-Þ][\wÀ-ÿ'’\- ]{2,30}?),\s+"
    r"(?:à|in|a)\s+([A-ZÀ-Þ][\wÀ-ÿ'’\- ]{2,30}?)\s*[,.]"
)

# Function words that mark a sentence as being about an officer. Used to
# label the relationship, never to invent one.
_ROLES = [
    (re.compile(r"verwaltungsrat", re.I), "board_member"),
    (re.compile(r"präsident|president|presidente", re.I), "chair"),
    (re.compile(r"geschäftsführ|gérant|gerente|amministrator", re.I), "managing_director"),
    (re.compile(r"direktor|directeur|directrice|direttor", re.I), "director"),
    (re.compile(r"prokurist|procurat", re.I), "authorised_officer"),
    (re.compile(r"gesellschafter|associé|socio", re.I), "shareholder"),
    (re.compile(r"liquidator|liquidateur|liquidatore", re.I), "liquidator"),
    (re.compile(r"revisionsstelle|organe de révision|ufficio di revisione", re.I), "auditor"),
]
_UID_RE = re.compile(r"\bCHE-\d{3}\.\d{3}\.\d{3}\b")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", m.group(1)))).strip()


def _block(xml: str, tag: str) -> str:
    """Return the inner XML of the first <tag>…</tag>, or ''.

    Scoping matters here: the document carries the *sending authority's*
    address in `meta/registrationOffice` (Bundesrain 20, 3003 Bern) before it
    carries the company's own. Reading `<street>` from the whole document
    therefore gave every Swiss company the Federal Office of Justice's
    address — which looked entirely plausible and was entirely wrong.
    """
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def _role_for(sentence: str) -> str:
    for pattern, role in _ROLES:
        if pattern.search(sentence):
            return role
    return "registered_officer"


def _people(pub_text: str) -> list[dict[str, str]]:
    """Extract officers, each with the sentence that names them."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.;])\s+", pub_text):
        for m in _PERSON_RE.finditer(sentence):
            name = re.sub(r"\s*,\s*", ", ", m.group(1)).strip()
            if len(name) < 4 or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({
                "name": name,
                "origin": m.group(2).strip(),
                "residence": m.group(3).strip(),
                "role": _role_for(sentence),
                # The evidence for the extraction, verbatim.
                "statement": sentence.strip()[:400],
            })
    return out


async def _detail(client: httpx.AsyncClient, pub_id: str) -> dict[str, Any] | None:
    try:
        r = await client.get(f"{BASE}/{pub_id}/xml")
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.info("shab: detail %s unavailable: %s", pub_id, e)
        return None
    xml = r.text
    pub_text = _text(xml, "publicationText")
    company_xml = _block(xml, "company")          # scoped — see _block()
    address_xml = _block(company_xml, "address")

    uid = _text(company_xml, "uid")
    if not uid:
        m = _UID_RE.search(pub_text)
        uid = m.group(0) if m else ""

    # `legalForm` is a numeric code (0111, 0106 …) with no published mapping
    # we can rely on. The publication text spells it out right after the UID
    # ("…, CHE-186.071.916, società anonima (Nr. FUSC…"), so take it from
    # there and keep the code as a secondary field rather than guessing.
    legal_form = ""
    if uid:
        m = re.search(re.escape(uid) + r",\s*([^(,]{3,70}?)\s*[(,]", pub_text)
        if m:
            legal_form = m.group(1).strip()

    return {
        "id": pub_id,
        "company": _text(company_xml, "name") or _text(xml, "displayName"),
        "translations": _text(company_xml, "translations"),
        "legal_form": legal_form,
        "legal_form_code": _text(company_xml, "legalForm"),
        "seat": _text(company_xml, "seat"),
        "street": _text(address_xml, "street"),
        "house_number": _text(address_xml, "houseNumber"),
        "postcode": _text(address_xml, "swissZipCode"),
        "town": _text(address_xml, "town"),
        # The cantonal register that issued it — not the federal office that
        # publishes the sheet.
        "registration_office": _text(_block(xml, "senderOffice"), "officeName"),
        "deletion_date": _text(_block(xml, "transaction"), "deletionDate"),
        "uid": uid,
        "text": pub_text,
        "people": _people(pub_text),
    }


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["shab_registry: empty search term"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        try:
            r = await client.get(BASE, params={
                "publicationStates": "PUBLISHED",
                "rubrics": "HR",                 # commercial register only
                "keyword": term,                 # see module docstring — NOT `query`
                "pageRequest.size": str(MAX_PUBLICATIONS),
            })
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            return [], [], [f"shab_registry: SHAB unreachable: {e}"]
        except ValueError:
            return [], [], ["shab_registry: non-JSON response from SHAB"]

        total = payload.get("total") or 0
        content = payload.get("content") or []
        if not content:
            return [], [], [f"{NOTE_PREFIX}shab_registry: no commercial-register "
                            f"publication mentions '{term}'."]

        # A term that matches a large share of the corpus is a sign the filter
        # did not bite (see the docstring). Say so rather than emitting noise.
        if total > 100_000:
            return [], [], [f"shab_registry: implausible result count ({total:,}) — "
                            "the search filter did not apply. Refusing to emit "
                            "findings that would not be about this term."]

        sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def fetch(pub_id: str):
            async with sem:
                return await _detail(client, pub_id)

        ids = [c["meta"]["id"] for c in content[:MAX_DETAIL] if c.get("meta", {}).get("id")]
        details = [d for d in await asyncio.gather(*[fetch(i) for i in ids]) if d]

    if total > len(content):
        errors.append(f"{NOTE_PREFIX}shab_registry: {total} publications matched, "
                      f"{len(content)} returned.")
    if len(content) > MAX_DETAIL:
        errors.append(f"{NOTE_PREFIX}shab_registry: full text read for the "
                      f"{MAX_DETAIL} most recent of {len(content)} publications.")

    # One company usually appears in several publications (incorporation,
    # each mutation, deletion). Emit it ONCE with the newest structured data
    # and every publication text as its history — a node per publication
    # would multiply the same company across the graph and bury the fact
    # that the entries describe a sequence.
    companies: dict[str, dict[str, Any]] = {}
    for d in details:
        name = d["company"] or term
        cur = companies.setdefault(name, {**d, "history": [], "all_people": []})
        # Officers must accumulate across publications, not follow the last
        # one: a deletion notice names nobody, so merging it last would erase
        # the very people the preceding mutation recorded.
        cur["all_people"].extend(d["people"])
        cur["history"].append({
            "publication": d["id"],
            "text": d["text"][:1200],
            "deletion_date": d["deletion_date"],
        })
        # Keep the richest structured values seen across the publications.
        for field in ("uid", "legal_form", "seat", "street", "house_number",
                      "postcode", "town", "registration_office", "deletion_date"):
            if not cur.get(field) and d.get(field):
                cur[field] = d[field]

    people_total = 0
    for company, d in companies.items():
        url = WEB.format(id=d["id"])
        address = " ".join(x for x in (d["street"], d["house_number"],
                                       d["postcode"], d["town"]) if x).strip()

        findings.append(Finding(
            entity_type="organization",
            label=company,
            url=url,
            confidence=0.95,
            data={
                "uid": d["uid"],
                "legal_form": d["legal_form"],
                "legal_form_code": d["legal_form_code"],
                "seat": d["seat"],
                "address": address,
                "town": d["town"],
                "translations": d["translations"],
                "registration_office": d["registration_office"],
                # A deleted entry is a fact in its own right: it dates the
                # end of the Swiss presence.
                "deleted_on": d["deletion_date"],
                "status": "deleted" if d["deletion_date"] else "registered",
                "register": "SHAB / commercial register (CH)",
                "publications": len(d["history"]),
                # The published wording is the evidence; keep it readable.
                "publication_text": d["text"][:2000],
                "publication_history": d["history"],
                "source": "shab",
            },
        ))
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}",
            to_entity=f"organization:{company}",
            relation="registered_as",
            confidence=0.9,
        ))

        if d["uid"]:
            findings.append(Finding(
                entity_type="company_id", label=d["uid"], url=url, confidence=0.95,
                data={"register": "UID (CH)", "company": company, "source": "shab"},
            ))
            edges.append(EdgeResult(
                from_entity=f"organization:{company}", to_entity=f"company_id:{d['uid']}",
                relation="has_identifier", confidence=0.95,
            ))

        if d["seat"] or d["town"]:
            place = d["seat"] or d["town"]
            findings.append(Finding(
                entity_type="location", label=place, url=url, confidence=0.85,
                data={"role": "registered seat", "address": address, "source": "shab"},
            ))
            edges.append(EdgeResult(
                from_entity=f"organization:{company}", to_entity=f"location:{place}",
                relation="seat_at", confidence=0.85,
            ))

        seen_people: set[str] = set()
        for p in d["all_people"]:
            if p["name"].lower() in seen_people:
                continue
            seen_people.add(p["name"].lower())
            people_total += 1
            findings.append(Finding(
                entity_type="person",
                label=p["name"],
                url=url,
                # Lower than the company: the company is a structured field,
                # the person is read out of prose.
                confidence=0.7,
                data={
                    "role": p["role"],
                    "origin": p["origin"],
                    "residence": p["residence"],
                    "company": company,
                    # What the register actually printed — check before relying.
                    "register_statement": p["statement"],
                    "extraction": "parsed from publication text, not a structured field",
                    "source": "shab",
                },
            ))
            edges.append(EdgeResult(
                from_entity=f"person:{p['name']}",
                to_entity=f"organization:{company}",
                relation=p["role"],
                confidence=0.7,
                data={"statement": p["statement"][:200]},
            ))

    if people_total:
        errors.append(f"{NOTE_PREFIX}shab_registry: {people_total} officer(s) parsed "
                      "from publication prose — each carries the sentence it came "
                      "from in `register_statement`; verify before relying on it.")
    return findings, edges, errors
