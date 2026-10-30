"""Swiss directory — tel.search.ch (keyless).

The register tells you a company exists and who signs for it. This tells you
**where it physically answers the phone**, which is a different and often more
operational fact: a branch office, a shared address with three other
companies, a number that also appears under a private name.

For a sanctions-evasion case the useful move is often the reverse one —
searching an address or a phone number rather than a name — because a
forwarding company and its front tend to share one of the two.

Covers Switzerland only, and only entries that are publicly listed: an
unlisted number is simply absent, which is not the same as not existing. The
runner says so rather than reporting a clean negative.

The API answers Atom. There is a `tel:` namespace in the schema but the
public endpoint does not populate it, so name, address and number are read
out of `title` and the `content` text block — the layout is stable:

    Muster Aviation SA
    Chemin de l'Exemple 1
    1200 Genève GE
    022 000 00 00
"""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

API = "https://tel.search.ch/api/"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 30
MAX_RESULTS = 20

ATOM = "{http://www.w3.org/2005/Atom}"
OS = "{http://a9.com/-/spec/opensearchrss/1.0/}"

log = logging.getLogger("module-corporate.telsearch")

# Swiss numbers as printed by the directory: "022 306 12 60", "+41 44 …"
_PHONE_RE = re.compile(r"(?:\+41[\s/]?|0)(?:\d[\s/]?){8,12}\d")
# "1215 Genève 15 Aéroport GE" — four-digit postcode starts the locality line
_PLACE_RE = re.compile(r"^(\d{4})\s+(.+)$")


def _clean_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("0") and len(digits) == 10:
        digits = "+41" + digits[1:]
    return digits


def _parse_entry(entry: ET.Element) -> dict:
    name = (entry.findtext(f"{ATOM}title") or "").strip()
    content = html.unescape(entry.findtext(f"{ATOM}content") or "")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]

    street = place = postcode = ""
    phones: list[str] = []
    for ln in lines[1:]:                      # line 0 repeats the title
        m = _PLACE_RE.match(ln)
        if m:
            postcode, place = m.group(1), m.group(2).strip()
            continue
        found = _PHONE_RE.findall(ln)
        if found and not re.search(r"[A-Za-zÀ-ÿ]{3}", ln):
            phones.extend(_clean_phone(p) for p in _PHONE_RE.finditer(ln)
                          for p in [p.group(0)])
            continue
        if not street:
            street = ln

    url = ""
    for link in entry.findall(f"{ATOM}link"):
        if link.get("rel") == "alternate" and link.get("type") == "text/html":
            url = link.get("href") or ""
            break

    return {"name": name, "street": street, "postcode": postcode,
            "place": place, "phones": sorted(set(p for p in phones if len(p) >= 9)),
            "url": url}


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["tel_search_ch: empty search term"]

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            r = await client.get(API, params={"was": term, "lang": "de",
                                              "maxnum": str(MAX_RESULTS)})
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except httpx.HTTPError as e:
            return [], [], [f"tel_search_ch: directory unreachable: {e}"]
        except ET.ParseError as e:
            return [], [], [f"tel_search_ch: malformed response: {e}"]

    total_txt = root.findtext(f"{OS}totalResults") or "0"
    try:
        total = int(total_txt)
    except ValueError:
        total = 0

    entries = [_parse_entry(e) for e in root.findall(f"{ATOM}entry")]
    entries = [e for e in entries if e["name"]]
    if not entries:
        return [], [], [f"{NOTE_PREFIX}tel_search_ch: no public Swiss directory "
                        f"entry for '{term}'. An unlisted number would also be "
                        "absent here — this is not proof of absence."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    root_type = "person" if query_type == "person_name" else "organization"

    for e in entries:
        address = " ".join(x for x in (e["street"], e["postcode"], e["place"]) if x)
        findings.append(Finding(
            entity_type=root_type, label=e["name"], url=e["url"] or None,
            confidence=0.8,
            data={"address": address, "street": e["street"], "postcode": e["postcode"],
                  "place": e["place"], "phones": e["phones"],
                  "directory": "tel.search.ch (CH)", "source": "tel_search_ch"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}", to_entity=f"{root_type}:{e['name']}",
            relation="listed_in_directory", confidence=0.8,
        ))

        for phone in e["phones"]:
            findings.append(Finding(
                entity_type="phone_number", label=phone, url=e["url"] or None,
                confidence=0.85,
                data={"holder": e["name"], "address": address,
                      "source": "tel_search_ch"},
            ))
            edges.append(EdgeResult(
                from_entity=f"{root_type}:{e['name']}",
                to_entity=f"phone_number:{phone}",
                relation="listed_phone", confidence=0.85,
            ))

        if e["place"]:
            findings.append(Finding(
                entity_type="location", label=e["place"], url=e["url"] or None,
                confidence=0.8,
                data={"postcode": e["postcode"], "street": e["street"],
                      "role": "directory address", "source": "tel_search_ch"},
            ))
            edges.append(EdgeResult(
                from_entity=f"{root_type}:{e['name']}",
                to_entity=f"location:{e['place']}",
                relation="located_at", confidence=0.8,
            ))

    errors: list[str] = []
    if total > len(entries):
        errors.append(f"{NOTE_PREFIX}tel_search_ch: {total} directory entries "
                      f"matched, {len(entries)} returned.")
    return findings, edges, errors
