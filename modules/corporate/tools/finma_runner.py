"""FINMA warning list — the Swiss regulator's list of unauthorised providers
(keyless).

Every other corporate source answers "does this company exist and what does
the register say". This one answers a question a register cannot: **has the
Swiss financial-market supervisor publicly warned about this name?** FINMA
publishes an entity here when it has concrete evidence that the entity
carries out an activity requiring authorisation without holding one — the
classic shape of an investment-fraud front. Over 2000 entries, reaching
back to 2009.

For the fraud cases this framework is built for, that makes it the single
highest-yield Swiss source in the module: a hit is not an indication that
something might be wrong, it is a supervisory authority saying in public
that it is.

Reliability A — a federal supervisory authority publishing about its own
mandate, with a citable page per entry.

⚠️  THE `ds` TRAP — READ BEFORE CHANGING THE QUERY
------------------------------------------------------------------
The list is rendered client-side from `POST /de/api/search/getresult`, a
Sitecore filter endpoint. Measured:

  * `GET` on that route → HTTP 405. It is POST-only.
  * The body must be **form-encoded**; a JSON body makes the endpoint hang
    until the client times out.
  * The source parameter is **`ds`**, not `source`. `source=<guid>` is
    accepted, answered 200, and returns `Count: 0` — a well-formed empty
    answer to a question the server never understood. A runner built on it
    would have reported "FINMA has never warned about this" for every
    selector ever searched.
  * An **empty** `query` is not the same as no `query`: `query=""` answers
    `Resultstring: "No valid Query"`, while omitting the key entirely
    returns the **whole list** (2302 rows, `Searchstring: "*"`).

That last point is why this runner carries a negative control. The failure
mode of a filter endpoint whose parameter name drifts is not an error — it
is a corpus dump that looks exactly like an enormous number of hits, which
is the entscheidsuche.ch failure `court_runner` was built to survive. One
extra request per run establishes that the filter still bites.

WHAT A HIT MEANS — AND WHAT IT DOES NOT
------------------------------------------------------------------
The search is a full-text index over the whole entry, not a name match.
Measured: `bitcoin` returns 5 entries of which 4 carry it in the name — the
fifth matched in the remarks. A domain of the form `example-ag.com` returns
dozens of rows, of which exactly one is the entry with that name; the rest
merely share the tokens `ag` and `com`.

So "FINMA returned this row" and "FINMA warned about the thing you searched
for" are different statements. This runner keeps them apart by fetching each
candidate's detail page and recording **which field the term actually
matched** — name, website, address or remarks — and deriving the confidence
from that (`_classify`). A row whose own fields carry the term nowhere
(`index_only`) is NOT reported: it is a warning about somebody else that the
index happened to return, and putting it in the graph would attach a fraud
warning to an unrelated party. The count of such rows goes into a note, so
"FINMA has nothing on this" stays distinguishable from "what came back was
about other people". Overstating any of this would put "FINMA warned about
this company" into a case file on the strength of a shared token.

⚠️  THE REMARKS NAME THE INNOCENT PARTY, NOT THE FRAUDSTER
------------------------------------------------------------------
`Bemerkungen` very often reads, in four languages:

    "https://example-ag.com/ is not related to the Example AG, Zurich, which
     is registered in the Swiss Commercial Register (CHE-000.000.000)."

The company name and the UID in that sentence belong to the **legitimate**
company being impersonated. Parsing them into nodes and linking them to the
warned entity would produce precisely the wrong graph: it would attach a
fraud warning to the victim of the name theft, and it would do so with a
formal identifier that merges cleanly with `zefix_registry`'s node for that
same company.

The remarks are therefore carried as text on the warning entry and are
**never parsed into entities**. If that ever changes, it must be by
extracting the "is not related to" pattern into an explicit
`not_related_to` relation — not by harvesting identifiers out of prose.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

SEARCH_URL = "https://www.finma.ch/de/api/search/getresult"
LIST_URL = "https://www.finma.ch/de/finma-public/warnungen/warnliste/"
SITE = "https://www.finma.ch"
# The Sitecore datasource id of the warning-list filter. Read from
# `data-source` on the `mod-filter` element of LIST_URL; if FINMA ever
# rebuilds the page this is the one value that has to be refreshed, and the
# negative control below is what will make its staleness visible.
DATASOURCE = "{1C6B8731-638C-4003-A93C-A625BF7A6800}"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
# Detail pages read in full per run. Candidates are ranked by name match
# first (`_rank`), so the entry that actually carries the search term is
# read even when the endpoint's own ordering changes.
MAX_DETAIL = 12
DETAIL_CONCURRENCY = 4
# Above this, the term is a token the corpus is full of ("swiss": 553) and
# the investigator is told so rather than shown twelve arbitrary rows.
BROAD_RESULT_HINT = 100

# The negative control. Must be a token FINMA cannot have printed.
_CONTROL_QUERY = "xyzzyfrobnicat qwertzuiop nichtexistent"

# One row of the detail table: <tr><th>Label</th><td>Value</td></tr>.
_ROW_RE = re.compile(r"<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>",
                     re.S | re.I)
_TABLE_RE = re.compile(r'<table[^>]*class="[^"]*\bvvg\b[^"]*"[^>]*>(.*?)</table>',
                       re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
# A host, with or without scheme/www and with or without a trailing path.
_HOST_RE = re.compile(
    r"(?:https?://)?(?:www\.)?([a-z0-9](?:[a-z0-9\-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+)", re.I)
# Multi-name titles: "Bitcoinch / bitcoinch.ai", "A / B / c.com" (312 of 2302).
_ALIAS_SPLIT_RE = re.compile(r"\s+/\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Tokens that carry no identity and must not create a match on their own.
# Measured need: `example-ag.com` and `sample-ag.com` share `ag` and `com`,
# which is the entire reason FINMA's index returns dozens of rows for such a
# domain. Legal forms are in here for the mirror case — "Muster Alpin GmbH"
# must still match the entry filed as "Muster Alpin".
_NOISE_TOKENS = frozenset({
    "com", "net", "org", "info", "online", "site", "xyz", "vip", "top",
    "shop", "app", "www", "http", "https", "biz", "club", "live", "pro",
    "gmbh", "ltd", "inc", "llc", "plc", "corp", "sarl", "sagl", "srl",
    "spa", "limited", "holding", "holdings", "company",
})
_MIN_TOKEN_LEN = 3

# Detail-table labels, German page. Matched by prefix, case-folded.
_F_NAME, _F_SEAT, _F_ADDRESS = "name", "sitz", "adresse"
_F_INTERNET, _F_HR, _F_REMARKS = "internet", "handelsregister", "bemerkungen"

# Values that are placeholders or statements about a missing value rather
# than a value. "Domizil am 20.01.2012 gelöscht" is a real, measured entry
# in the Adresse column — geocoding it would be nonsense.
_EMPTY_VALUES = {"", "-", "–", "—", "n/a", "k.a.", "unbekannt", "keine"}
_NON_PLACE_MARKERS = ("gelöscht", "geloescht", "unbekannt", "domizil am",
                      "keine angabe", "nicht bekannt")

# Where the search term was found → (confidence, caveat). The ordering of
# `_classify` matters: name beats website beats address beats remarks.
_MATCH_GRADES: dict[str, tuple[float, str]] = {
    "name_exact": (0.95, "The FINMA entry is filed under exactly this name."),
    "name": (0.9, "The search term appears in the name FINMA filed the entry "
                  "under."),
    "website": (0.85, "The search term appears in the website FINMA lists for "
                      "this entry."),
    "address": (0.6, "The search term matched only the seat or address of the "
                     "entry — a shared address is a lead, not an identity."),
    "remarks": (0.5, "The search term appears only in FINMA's remarks. Those "
                     "frequently name the LEGITIMATE company being "
                     "impersonated — read the entry before concluding the "
                     "warning is about the searched party."),
    "index_only": (0.4, "The entry was returned by FINMA's full-text index, "
                        "but the search term appears in none of its listed "
                        "fields. Treat as unconfirmed."),
}

log = logging.getLogger("module-corporate.finma")


def _clean(raw: str) -> str:
    """Tag-strip, unescape and collapse one HTML cell."""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", raw or ""))).strip()


def _loose(value: str) -> str:
    """Comparison form: case-folded, punctuation removed.

    "example-ag.com", "Example AG.com" and "EXAMPLEAGCOM" compare equal. Used only
    for deciding WHERE a term matched, never for a node label.
    """
    return _NON_ALNUM_RE.sub("", (value or "").casefold())


def _tokens(value: str) -> set[str]:
    """Identity-bearing tokens of a name. See `_NOISE_TOKENS`."""
    return {t for t in _NON_ALNUM_RE.split((value or "").casefold())
            if len(t) >= _MIN_TOKEN_LEN and t not in _NOISE_TOKENS}


def _is_empty(value: str) -> bool:
    return (value or "").strip().casefold() in _EMPTY_VALUES


def _looks_like_place(value: str) -> bool:
    """Is this Adresse/Sitz cell an actual place, or a note about one?"""
    if _is_empty(value) or len(value.strip()) < 3:
        return False
    low = value.casefold()
    return not any(marker in low for marker in _NON_PLACE_MARKERS)


def _hosts(value: str) -> list[str]:
    """Every host in a cell, normalised (lowercase, no scheme, no www).

    The Internet column holds anything from "-" through "www.m1lux.AG" to
    two URLs separated by a slash, so it is scanned rather than parsed.
    """
    if _is_empty(value):
        return []
    out: list[str] = []
    for m in _HOST_RE.finditer(value):
        host = m.group(1).lower().rstrip(".")
        # A TLD of one character, or an all-numeric last label, is a false
        # positive from a version number or a truncated sentence.
        tld = host.rsplit(".", 1)[-1]
        if len(tld) < 2 or tld.isdigit():
            continue
        if host not in out:
            out.append(host)
    return out


def _is_hostlike(value: str) -> bool:
    """Is this whole string a bare domain/URL rather than a company name?

    336 of the 2302 titles are: FINMA files a pure web operation under its
    domain. Those become `domain` nodes, so they merge with what the infra
    module already knows about the same host instead of becoming an
    `organization` twin of it.
    """
    stripped = (value or "").strip().rstrip("/")
    if not stripped or " " in stripped:
        return False
    m = _HOST_RE.fullmatch(stripped)
    return bool(m)


def _parse_date(value: Any) -> "datetime | None":
    """The date FINMA published the entry — a real source date.

    `found_at` means "when the source said it". A warning-list entry is
    dated (dd.mm.yyyy), so the case timeline can place the warning at the
    day it was issued instead of the day we searched.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%d.%m.%Y")
    except ValueError:
        return None


async def _search(client: httpx.AsyncClient, term: str) -> dict[str, Any]:
    """One filter query. `term` empty → the whole list (see the docstring)."""
    data = {"ds": DATASOURCE}
    if term:
        data["query"] = term
    r = await client.post(SEARCH_URL, data=data)
    r.raise_for_status()
    return r.json()


async def _filter_alive(client: httpx.AsyncClient) -> bool:
    """Negative control: does the endpoint still actually filter?

    Costs one request and is the difference between "FINMA has never warned
    about this" and "the query parameter is being ignored and we are looking
    at the entire 2300-row list". Returns False when a phrase that cannot
    exist still produces rows — at which point this runner refuses.
    """
    try:
        payload = await _search(client, _CONTROL_QUERY)
    except Exception as e:  # noqa: BLE001 — deliberately every exception
        # Could not establish it either way. Treat as NOT alive: refusing on
        # an unproven filter is the safe direction, because the failure this
        # guards against is silent and looks like a very good result.
        #
        # Broad on purpose, for the same reason as court_runner's control:
        # the guard's value is that it holds when something upstream changes,
        # so it must not depend on the exception taxonomy of what it guards.
        log.info("finma_warnlist: negative control could not run: %s", e)
        return False
    count = payload.get("Count") or 0
    if count:
        log.error("finma_warnlist: NEGATIVE CONTROL FAILED — the control phrase "
                  "returned %s rows; the endpoint is not filtering", count)
        return False
    return True


async def _detail(client: httpx.AsyncClient, link: str) -> dict[str, str]:
    """Read one warning-list entry page into its labelled fields."""
    try:
        r = await client.get(f"{SITE}{link}")
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.info("finma_warnlist: detail page %s unreachable: %s", link, e)
        return {}
    table = _TABLE_RE.search(r.text)
    if not table:
        return {}
    fields: dict[str, str] = {}
    for label, value in _ROW_RE.findall(table.group(1)):
        key = _clean(label).casefold()
        val = _clean(value)
        for probe in (_F_NAME, _F_SEAT, _F_ADDRESS, _F_INTERNET, _F_HR,
                      _F_REMARKS):
            if key.startswith(probe):
                fields[probe] = val
                break
    return fields


def _classify(term: str, name: str, fields: dict[str, str]) -> tuple[str, float, str]:
    """Where did the search term actually match? See the module docstring.

    Names are compared on identity-bearing TOKENS, not on raw substrings.
    Substring alone is both too generous and too strict here: too generous
    because `example-ag.com` and `sample-ag.com` share `ag`/`com`, too strict
    because "Muster Alpin GmbH" is not a substring of the entry FINMA filed
    as "Muster Alpin". The subset test in either direction handles both —
    a searched name that adds a legal form still matches, a row that merely
    shares a top-level domain does not.
    """
    loose_term = _loose(term)
    loose_name = _loose(name)
    term_tok, name_tok = _tokens(term), _tokens(name)
    if loose_term and loose_term == loose_name:
        grade = "name_exact"
    elif term_tok and name_tok and (term_tok <= name_tok or name_tok <= term_tok):
        grade = "name"
    elif loose_term and loose_term in loose_name:
        grade = "name"
    elif loose_term and loose_term in _loose(fields.get(_F_INTERNET, "")):
        grade = "website"
    elif loose_term and (loose_term in _loose(fields.get(_F_ADDRESS, ""))
                         or loose_term in _loose(fields.get(_F_SEAT, ""))):
        grade = "address"
    elif loose_term and loose_term in _loose(fields.get(_F_REMARKS, "")):
        grade = "remarks"
    else:
        grade = "index_only"
    confidence, caveat = _MATCH_GRADES[grade]
    return grade, confidence, caveat


def _rank(items: list[dict[str, Any]], term: str) -> list[dict[str, Any]]:
    """Name matches first, then the endpoint's own order.

    The endpoint appears to rank by relevance, but "appears to" is not a
    guarantee, and MAX_DETAIL cuts the list. Sorting the candidates that
    carry the term in their title to the front means the entry the
    investigator is actually looking for is the one read in full.
    """
    loose_term = _loose(term)

    def key(pair: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        idx, item = pair
        title = _loose(str(item.get("Title") or ""))
        if loose_term and loose_term == title:
            rank = 0
        elif loose_term and loose_term in title:
            rank = 1
        else:
            rank = 2
        return rank, idx

    return [item for _, item in sorted(enumerate(items), key=key)]


def _entity_for(segment: str) -> tuple[str, str] | None:
    """One title segment → (entity_type, label), or None if unusable."""
    text = (segment or "").strip().rstrip("/")
    if not text:
        return None
    if _is_hostlike(text):
        hosts = _hosts(text)
        return ("domain", hosts[0]) if hosts else None
    return ("organization", text[:200])


def _entry_findings(item: dict[str, Any], fields: dict[str, str], term: str,
                    query_type: str,
                    ) -> tuple[list[Finding], list[EdgeResult], str]:
    """One warning-list row → its nodes, its edges, and how it matched.

    The grade travels back to the caller because it decides whether the row
    is reported at all: an `index_only` row matched FINMA's full-text index
    in none of the entry's own fields and is noise, not a warning.
    """
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    title = str(item.get("Title") or "").strip()
    name = fields.get(_F_NAME) or title
    if not name:
        return [], [], "index_only"

    link = str(item.get("Link") or "")
    url = f"{SITE}{link}" if link.startswith("/") else (link or LIST_URL)
    listed_on = _parse_date(item.get("Date"))
    hr_status = fields.get(_F_HR, "") or str(item.get("FacetColumn") or "")
    grade, confidence, caveat = _classify(term, name, fields)
    if grade == "index_only":
        # Nothing in this entry carries the term. Reporting it would put an
        # unrelated fraud warning next to the searched party in the graph;
        # the caller counts it into a note instead of dropping it silently.
        return [], [], grade

    # The entry itself: one node per warning, never merged away.
    #
    # This is deliberate. graph_builder keeps the FIRST finding for a given
    # `type:label` key and credits later ones only as contributing tools —
    # node `data` is NOT merged. Carrying the warning solely as fields on the
    # `organization` node would mean that whenever zefix_registry or
    # shab_registry reported the same company first, the warning silently
    # vanished from the graph and only the tool credit remained. A distinct
    # `warning_entry` node cannot be swallowed that way, and the `listed_on`
    # edge keeps the fact visible even so.
    entry_label = title or name
    if len(entry_label) > 200:
        entry_label = entry_label[:197] + "…"

    findings.append(Finding(
        entity_type="warning_entry",
        label=entry_label,
        url=url,
        confidence=confidence,
        found_at=listed_on,
        data={
            "authority": "FINMA (Swiss Financial Market Supervisory Authority)",
            "list": "Warnliste — providers acting without the required "
                    "authorisation",
            "listed_since": item.get("Date") or None,
            "name": name,
            "seat": fields.get(_F_SEAT) or None,
            "address": fields.get(_F_ADDRESS) or None,
            "website": fields.get(_F_INTERNET) or None,
            "commercial_register": hr_status or None,
            # Read the docstring before parsing this into entities: the names
            # and UIDs in here usually belong to the impersonated company.
            "remarks": (fields.get(_F_REMARKS) or "")[:2000] or None,
            "match_field": grade,
            "caveat": caveat,
            "register": "FINMA Warnliste (CH)",
            "source": "finma",
        },
    ))

    # The warned party. `organization`, or `domain` when FINMA filed the
    # entry under a bare host — so it merges with what the infra module
    # knows about that host instead of standing next to it as a twin.
    primary = _entity_for(_ALIAS_SPLIT_RE.split(title or name)[0])
    if primary is None:
        primary = ("organization", name[:200])
    p_type, p_label = primary

    findings.append(Finding(
        entity_type=p_type,
        label=p_label,
        url=url,
        confidence=confidence,
        found_at=listed_on,
        data={
            "finma_warning": True,
            "listed_since": item.get("Date") or None,
            "commercial_register": hr_status or None,
            # An entry "Ohne HR-Eintrag" is a finding in itself: the other
            # two register tools in this module will legitimately find
            # nothing, and that absence must not read as a failed lookup.
            "note": ("No Swiss commercial-register entry — zefix_registry and "
                     "shab_registry will not find this party."
                     if "ohne" in hr_status.casefold() else None),
            "caveat": caveat,
            "register": "FINMA Warnliste (CH)",
            "source": "finma",
        },
    ))
    edges.append(EdgeResult(
        from_entity=f"{p_type}:{p_label}",
        to_entity=f"warning_entry:{entry_label}",
        relation="listed_on", confidence=confidence,
    ))
    # ...and back to what the investigator typed — unless that IS this node.
    # Searching a domain such as `example-ag.com` produces a root key identical to
    # the primary node's key, and an edge from a node to itself renders as a
    # loop that says nothing.
    if f"{query_type}:{term}" != f"{p_type}:{p_label}":
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}",
            to_entity=f"{p_type}:{p_label}",
            relation="matches_warning_entry", confidence=confidence,
        ))

    # The other names in the title. FINMA writes them as "Name / domain.tld"
    # and they are exactly what an investigator needs: the same operation
    # renaming itself, or the site it runs under.
    seen = {(p_type, p_label)}
    for segment in _ALIAS_SPLIT_RE.split(title)[1:]:
        alias = _entity_for(segment)
        if alias is None or alias in seen:
            continue
        seen.add(alias)
        a_type, a_label = alias
        findings.append(Finding(
            entity_type=a_type, label=a_label, url=url, confidence=confidence,
            found_at=listed_on,
            data={"finma_warning": True, "role": "further name on the same "
                  "FINMA entry", "listed_as": title,
                  "register": "FINMA Warnliste (CH)", "source": "finma"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{p_type}:{p_label}", to_entity=f"{a_type}:{a_label}",
            # A company and its site are in an operating relation; two hosts
            # on one entry ("emasan-ag.com / emasanag.com") are the same
            # operation spelled twice, which is an alias.
            relation=("operates_website"
                      if a_type == "domain" and p_type != "domain" else "alias_of"),
            confidence=confidence,
        ))

    # The website column, which is often a host the title does not carry.
    for host in _hosts(fields.get(_F_INTERNET, "")):
        if ("domain", host) in seen:
            continue
        seen.add(("domain", host))
        findings.append(Finding(
            entity_type="domain", label=host, url=url, confidence=confidence,
            found_at=listed_on,
            data={"finma_warning": True,
                  "role": "website FINMA lists for this entry",
                  "listed_as": title, "register": "FINMA Warnliste (CH)",
                  "source": "finma"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{p_type}:{p_label}", to_entity=f"domain:{host}",
            relation="operates_website" if p_type != "domain" else "alias_of",
            confidence=confidence,
        ))

    # Seat and address, as one location — the handover to geo_ch, which
    # resolves it to a building and a parcel. Same shape zefix_registry
    # emits for a registered seat, so the two chain identically.
    address, seat = fields.get(_F_ADDRESS, ""), fields.get(_F_SEAT, "")
    parts = [p for p in (address if _looks_like_place(address) else "",
                         seat if _looks_like_place(seat) else "") if p]
    if parts:
        place = ", ".join(parts)
        findings.append(Finding(
            entity_type="location", label=place[:200], url=url,
            confidence=confidence, found_at=listed_on,
            data={"role": "address on the FINMA warning entry",
                  "municipality": seat or None, "listed_as": title,
                  "register": "FINMA Warnliste (CH)", "source": "finma"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{p_type}:{p_label}", to_entity=f"location:{place[:200]}",
            relation="seat_at", confidence=confidence,
        ))
    return findings, edges, grade


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["finma_warnlist: empty search term"]
    if len(term) < 3:
        return [], [], ["finma_warnlist: search term too short — a one- or "
                        "two-character term matches arbitrary rows in the "
                        "full-text index and would return noise, not findings."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                 "X-Requested-With": "XMLHttpRequest", "Referer": LIST_URL},
    ) as client:
        if not await _filter_alive(client):
            return [], [], [
                "finma_warnlist: the warning-list endpoint answered a term "
                "that cannot exist, i.e. it is returning the whole list "
                "instead of search results. Refusing to emit findings that "
                f"would not be about this term. (Check {LIST_URL} — the "
                "filter's `ds` datasource id may have changed; see the runner "
                "docstring.)"
            ]

        try:
            payload = await _search(client, term)
        except httpx.HTTPError as e:
            return [], [], [f"finma_warnlist: FINMA unreachable: {e}"]
        except ValueError as e:
            return [], [], [f"finma_warnlist: unreadable response from FINMA: {e}"]

        if payload.get("Resultstring") == "No valid Query":
            return [], [], ["finma_warnlist: FINMA rejected the query as "
                            "invalid. The filter contract has changed — see "
                            "the runner docstring."]

        items = payload.get("Items") or []
        count = payload.get("Count") or len(items)
        if not items:
            return [], [], [f"{NOTE_PREFIX}finma_warnlist: no FINMA warning-list "
                            f"entry matches '{term}'."]

        candidates = _rank(items, term)[:MAX_DETAIL]
        sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def fetch(item: dict[str, Any]) -> dict[str, str]:
            async with sem:
                return await _detail(client, str(item.get("Link") or ""))

        details = await asyncio.gather(*[fetch(i) for i in candidates])

    if count > len(candidates):
        errors.append(
            f"{NOTE_PREFIX}finma_warnlist: {count} entries matched; the "
            f"{len(candidates)} closest to the term were read in full."
            + (" The term matches a large part of the list — narrow it to see "
               "the rest." if count > BROAD_RESULT_HINT else ""))

    graded: dict[str, int] = {}
    for item, fields in zip(candidates, details):
        # A detail page that could not be read still leaves the search row,
        # which carries the name, the date and the register status — enough
        # for a usable finding, and better than dropping a real warning.
        f, e, grade = _entry_findings(item, fields or {}, term, query_type)
        graded[grade] = graded.get(grade, 0) + 1
        findings.extend(f)
        edges.extend(e)

    dropped = graded.pop("index_only", 0)
    reported = sum(graded.values())
    if dropped:
        # Never a silent cap: the investigator is told what was left out and
        # why, so "FINMA has nothing on this" can be told apart from "the
        # rows FINMA returned were about other parties".
        errors.append(
            f"{NOTE_PREFIX}finma_warnlist: {dropped} of the {dropped + reported} "
            f"entries read matched only FINMA's full-text index and carry the "
            f"term in none of their own fields (name, website, address, "
            f"remarks). Not reported — they are other parties' warnings.")
    if reported:
        strong = graded.get("name_exact", 0) + graded.get("name", 0)
        errors.append(
            f"{NOTE_PREFIX}finma_warnlist: {reported} warning-list "
            f"entr{'y' if reported == 1 else 'ies'} reported, {strong} of them "
            f"matching in the name. Each finding records in `match_field` "
            f"where the term was found; an entry matching only in the remarks "
            f"often names the impersonated company rather than the warned one.")
    return findings, edges, errors
