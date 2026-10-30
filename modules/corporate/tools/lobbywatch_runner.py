"""Lobbywatch — who sits on whose board, and who gets into the Bundeshaus.

The gap this fills
------------------
Every other source in `corporate` answers a question about a COMPANY: what
the register published (`shab_registry`), what it currently says
(`zefix_registry`), whether a court ruled (`court_decisions`), whether the
supervisor warned (`finma_warnlist`), who owns whom across borders
(`gleif_lei`). None of them answers the question a procurement or
influence case actually turns on: **which sitting politician is attached to
this company, and in what role.**

Lobbywatch maintains exactly that register for Switzerland — 243 members of
parliament, 973 lobbyists, 10 215 organisations, 7 581 declared interest
ties, 1 953 mandates and, uniquely, the **334 Bundeshaus access badges**:
every parliamentarian may hand out two, and Lobbywatch records who received
them. Nothing else in this framework can produce a person→person edge of
that kind.

Why the UID matters more than the names
---------------------------------------
6 356 of the 10 215 organisations carry their commercial-register **UID**
(`CHE-…`). That is the same key `zefix_registry` and `shab_registry` emit as
`company_id`, so a lobby tie lands on the SAME node as the register data
rather than beside it. Searching a company by UID therefore answers "who
from parliament is on this board" inside the graph the investigator already
has open.

What was measured before this was built
---------------------------------------
* **`bis` is not an end date here.** 0 of 7 581 interest ties and 1 of 1 953
  mandates carry one. Lobbywatch expresses "this tie ended" by REMOVING the
  row, not by dating it. Consequence, and it is stated in every finding:
  this source answers *what is true now*. It cannot answer "was she on that
  board in 2019", and a runner that presented a null `bis` as "still
  running, verified" would be inventing a claim the data does not make.
* **`status` separates `deklariert` from `nicht-deklariert`.** An
  undeclared tie is the investigative one — the whole point of the register
  — so it travels as its own field and is never flattened away.
* **Each tie carries `quelle_url`**, frequently a cantonal commercial-register
  extract. That becomes the finding's `url`, so the claim is citable back to
  a primary document rather than to Lobbywatch's word.

Reliability B, deliberately not A
---------------------------------
A is reserved here for a primary record — a register publication, a signed
judgment, a supervisor's own warning list. Lobbywatch is a well-sourced
volunteer NGO register with per-entry provenance and an authorisation date,
which is strong, but it is a compilation about third parties. B says
"usually reliable" and that is the honest slot. The `quelle_url` lets the
analyst upgrade any single finding to A by opening the register extract.

Loading and caching
-------------------
The weekly flat export is one 4.8 MB ZIP of 19 JSON tables. It is fetched
once and held in memory for CACHE_TTL; a container restart re-fetches. That
is the right trade for a dataset that changes on Monday mornings.

⚠️ **A failed load is an error, never an empty result.** "This person has no
lobby ties" is a substantive claim about a politician. Reporting it because
a download failed would be the worst failure this tool could have, so the
load path returns an error and no findings.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import unicodedata
import zipfile
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

log = logging.getLogger("module-corporate.lobbywatch")

EXPORT_URL = ("https://cms.lobbywatch.ch/sites/lobbywatch.ch/files/exports/"
              "lobbywatch_export_flat.json.zip")
SOURCE_PAGE = "https://lobbywatch.ch/de/daten"
PROFILE_URL = "https://lobbywatch.ch/de/daten/parlamentarier/{id}"
ORG_URL = "https://lobbywatch.ch/de/daten/organisation/{id}"
TIMEOUT = 120
CACHE_TTL = 24 * 3600          # the export is rebuilt Monday mornings
MAX_TIES = 60                  # per direction

_TABLES = ("parlamentarier", "person", "organisation", "interessenbindung",
           "mandat", "zutrittsberechtigung", "partei", "rat", "kanton",
           "interessengruppe")

_cache: dict[str, Any] = {"at": 0.0, "data": None}
_lock = asyncio.Lock()


# ------------------------------------------------------------------ loading
def _parse_zip(blob: bytes) -> dict[str, list[dict]]:
    z = zipfile.ZipFile(io.BytesIO(blob))
    out: dict[str, list[dict]] = {}
    for t in _TABLES:
        name = f"flat_{t}.json"
        if name not in z.namelist():
            raise ValueError(f"table '{name}' missing from the export")
        rows = json.loads(z.read(name).decode("utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"table '{name}' is not a list")
        out[t] = rows
    # A structural sanity check, not a size check: the export could shrink
    # legitimately, but a parliament with no members means the format moved.
    if not out["parlamentarier"] or not out["organisation"]:
        raise ValueError("the export parsed but carries no parliamentarians "
                         "or organisations — the format has changed")
    return out


async def _load() -> dict[str, list[dict]]:
    async with _lock:
        if _cache["data"] is not None and (time.time() - _cache["at"]) < CACHE_TTL:
            return _cache["data"]
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": "OOF/1.0"}) as c:
            r = await c.get(EXPORT_URL)
        if r.status_code != 200:
            raise RuntimeError(f"export download returned HTTP {r.status_code}")
        data = await asyncio.to_thread(_parse_zip, r.content)
        _cache.update(at=time.time(), data=data)
        log.info("lobbywatch export loaded: %s",
                 {k: len(v) for k, v in data.items()})
        return data


# ----------------------------------------------------------------- matching
def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _uid(s: Any) -> str:
    """CHE-114.321.043 / CHE114321043 → che114321043."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _name_keys(row: dict) -> set[str]:
    first, last = row.get("vorname"), row.get("nachname")
    keys = {_norm(row.get(k)) for k in ("anzeige_name", "name", "name_de")}
    if first and last:
        keys.add(_norm(f"{first} {last}"))
        keys.add(_norm(f"{last} {first}"))
    return {k for k in keys if k}


def _match_people(rows: list[dict], term: str) -> tuple[list[dict], str]:
    """Exact full-name match first; only fall back to surname alone."""
    t = _norm(term)
    exact = [r for r in rows if t in _name_keys(r)]
    if exact:
        return exact, "exact"
    surname = [r for r in rows if _norm(r.get("nachname")) == t]
    if surname:
        return surname, "surname_only"
    # Last resort: the term appears as a whole word inside the display name.
    loose = [r for r in rows
             if re.search(rf"\b{re.escape(t)}\b", _norm(r.get("anzeige_name")))]
    return loose, "partial" if loose else "none"


def _match_orgs(rows: list[dict], term: str, by_uid: bool) -> tuple[list[dict], str]:
    if by_uid:
        u = _uid(term)
        hit = [r for r in rows if _uid(r.get("uid")) == u]
        return hit, "uid" if hit else "none"
    t = _norm(term)
    fields = ("anzeige_name", "name", "name_de", "name_fr", "name_it",
              "abkuerzung_de", "abkuerzung_fr", "alias_namen_de")
    exact = [r for r in rows if any(_norm(r.get(f)) == t for f in fields)]
    if exact:
        return exact, "exact"
    loose = [r for r in rows
             if re.search(rf"\b{re.escape(t)}\b", _norm(r.get("anzeige_name")))]
    return loose, "partial" if loose else "none"


# ------------------------------------------------------------------ output
def _org_finding(org: dict, extra: dict) -> Finding:
    data = {
        "seat": org.get("ort"),
        "legal_form": org.get("rechtsform_handelsregister") or org.get("rechtsform"),
        "in_commercial_register": bool(org.get("in_handelsregister")),
        "inactive": bool(org.get("inaktiv")),
        "uid": org.get("uid"),
        "source": "lobbywatch",
        **extra,
    }
    return Finding(entity_type="organization",
                   label=org.get("anzeige_name") or org.get("name") or "?",
                   confidence=0.75, platform="lobbywatch",
                   url=ORG_URL.format(id=org.get("id")), data=data)


def _tie_data(tie: dict, lookup: dict) -> dict:
    return {
        "role": tie.get("art"),
        "function": tie.get("funktion_im_gremium"),
        "declaration": tie.get("status"),
        "declaration_duty": tie.get("deklarationstyp"),
        "main_occupation": bool(tie.get("hauptberuflich")),
        "description": tie.get("beschreibung"),
        "since": tie.get("von"),
        # Measured: `bis` is unset on every current row — an ended
        # tie is DELETED from the export, not dated. Carried verbatim so the
        # field never reads as a verified "still running".
        "until": tie.get("bis"),
        "currency_note": "lobbywatch lists current ties only; ended ties are "
                         "removed rather than dated",
        "authorised": tie.get("autorisiert_datum"),
        "source": "lobbywatch",
        **lookup,
    }


# -------------------------------------------------------------------- main
async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "person_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["lobbywatch_ties: empty search term"]

    try:
        d = await _load()
    except Exception as e:  # noqa: BLE001
        # Deliberately an ERROR: an empty result here would read as
        # "this person has no lobby ties", which is a claim, not a silence.
        return [], [], [f"lobbywatch_ties: could not load the Lobbywatch export "
                        f"({type(e).__name__}: {e}) — no conclusion is reported, "
                        f"because 'no ties found' and 'could not look' are "
                        f"different answers. Source: {SOURCE_PAGE}"]

    parl = {r["id"]: r for r in d["parlamentarier"]}
    pers = {r["id"]: r for r in d["person"]}
    orgs = {r["id"]: r for r in d["organisation"]}
    party = {r["id"]: r.get("abkuerzung") for r in d["partei"]}
    rat = {r["id"]: r.get("name_de") for r in d["rat"]}
    kanton = {r["id"]: r.get("abkuerzung") for r in d["kanton"]}

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    capped = 0

    if query_type in ("company_name", "company_id"):
        hits, how = _match_orgs(list(orgs.values()), term,
                                by_uid=(query_type == "company_id"))
        if not hits:
            return findings, edges, [
                f"{NOTE_PREFIX}lobbywatch_ties: no organisation in Lobbywatch's "
                f"{len(orgs)} entries matches '{term}'. The register covers "
                "organisations with a political tie, not the whole commercial "
                "register — an absence here says nothing about the company."]
        if how == "partial":
            errors.append(f"{NOTE_PREFIX}lobbywatch_ties: no exact organisation name "
                          f"matched '{term}'; {len(hits)} entry/entries matched on a "
                          "word within the name.")
        root = f"{'company_id' if query_type == 'company_id' else 'company_name'}:{term}"

        for org in hits[:10]:
            org_label = org.get("anzeige_name") or org.get("name")
            org_key = f"organization:{org_label}"
            findings.append(_org_finding(org, {"match": how}))
            # No root edge when the matched organisation IS the searched name.
            # `TYPE_MAP` folds `company_name:X` and `organization:X` into one
            # node, so that edge would be a loop on the very node the analyst
            # is looking at. `build_graph` drops it centrally;
            # not emitting it keeps the runner from relying on that guard —
            # and the merge already states the relation the edge would.
            if _norm(org_label) != _norm(term):
                edges.append(EdgeResult(from_entity=root, to_entity=org_key,
                                        relation="listed_by_lobbywatch",
                                        confidence=0.75))
            # The UID is the join to zefix/shab. Emitted as its own node so it
            # merges with the register data instead of sitting inside `data`.
            if org.get("uid"):
                findings.append(Finding(
                    entity_type="company_id", label=org["uid"], confidence=0.8,
                    platform="lobbywatch", url=ORG_URL.format(id=org.get("id")),
                    data={"source": "lobbywatch", "organisation": org.get("anzeige_name")}))
                edges.append(EdgeResult(from_entity=org_key,
                                        to_entity=f"company_id:{org['uid']}",
                                        relation="registered_as", confidence=0.8))

            for tie in d["interessenbindung"]:
                if tie.get("organisation_id") != org.get("id"):
                    continue
                p = parl.get(tie.get("parlamentarier_id"))
                if not p:
                    continue
                if len(findings) >= MAX_TIES * 2:
                    capped += 1
                    continue
                name = p.get("anzeige_name") or p.get("name")
                findings.append(Finding(
                    entity_type="person", label=name, confidence=0.8,
                    platform="lobbywatch",
                    url=tie.get("quelle_url") or PROFILE_URL.format(id=p.get("id")),
                    data=_tie_data(tie, {
                        "kind": "member of parliament",
                        "chamber": rat.get(p.get("rat_id")),
                        "canton": kanton.get(p.get("kanton_id")),
                        "party": party.get(p.get("partei_id")),
                        "in_parliament_since": p.get("im_rat_seit"),
                        "organisation": org.get("anzeige_name"),
                    })))
                edges.append(EdgeResult(
                    from_entity=f"person:{name}", to_entity=org_key,
                    relation=tie.get("art") or "interest_tie", confidence=0.8))

            for m in d["mandat"]:
                if m.get("organisation_id") != org.get("id"):
                    continue
                pp = pers.get(m.get("person_id"))
                if not pp:
                    continue
                if len(findings) >= MAX_TIES * 2:
                    capped += 1
                    continue
                name = pp.get("anzeige_name") or pp.get("name")
                findings.append(Finding(
                    entity_type="person", label=name, confidence=0.75,
                    platform="lobbywatch", url=m.get("quelle_url"),
                    data=_tie_data(m, {"kind": "lobbyist / mandate holder",
                                       "occupation": pp.get("beruf"),
                                       "organisation": org.get("anzeige_name")})))
                edges.append(EdgeResult(
                    from_entity=f"person:{name}", to_entity=org_key,
                    relation=m.get("art") or "mandate", confidence=0.75))

    else:                                            # person_name / keyword
        cands = list(parl.values()) + list(pers.values())
        hits, how = _match_people(cands, term)
        if not hits:
            return findings, edges, [
                f"{NOTE_PREFIX}lobbywatch_ties: '{term}' appears in neither the 243 "
                f"parliamentarians nor the {len(pers)} recorded lobbyists. That is "
                "the expected answer for anyone outside federal politics — it is "
                "not a statement about the person."]
        if how != "exact":
            errors.append(f"{NOTE_PREFIX}lobbywatch_ties: no exact full-name match for "
                          f"'{term}'; matched {len(hits)} person(s) by "
                          f"{'surname alone' if how == 'surname_only' else 'partial name'}"
                          " — check the identity before using these ties.")

        for p in hits[:8]:
            is_parl = "im_rat_seit" in p
            name = p.get("anzeige_name") or p.get("name")
            pkey = f"person:{name}"
            findings.append(Finding(
                entity_type="person", label=name,
                confidence=0.8 if how == "exact" else 0.5,
                platform="lobbywatch", url=PROFILE_URL.format(id=p.get("id")),
                data={
                    "kind": "member of parliament" if is_parl else "lobbyist / mandate holder",
                    "chamber": rat.get(p.get("rat_id")) if is_parl else None,
                    "canton": kanton.get(p.get("kanton_id")) if is_parl else None,
                    "party": party.get(p.get("partei_id")),
                    "committees": p.get("kommissionen") or p.get("parlamentarier_kommissionen"),
                    "occupation": p.get("beruf"),
                    "in_parliament_since": p.get("im_rat_seit"),
                    "match": how, "source": "lobbywatch",
                }))

            rows = ([(t, "interessenbindung") for t in d["interessenbindung"]
                     if is_parl and t.get("parlamentarier_id") == p.get("id")]
                    + [(m, "mandat") for m in d["mandat"]
                       if not is_parl and m.get("person_id") == p.get("id")])
            for tie, _kind in rows[:MAX_TIES]:
                org = orgs.get(tie.get("organisation_id"))
                if not org:
                    continue
                org_key = f"organization:{org.get('anzeige_name') or org.get('name')}"
                findings.append(_org_finding(org, _tie_data(tie, {"person": name})))
                edges.append(EdgeResult(
                    from_entity=pkey, to_entity=org_key,
                    relation=tie.get("art") or "interest_tie",
                    confidence=0.8 if how == "exact" else 0.5))
                if org.get("uid"):
                    findings.append(Finding(
                        entity_type="company_id", label=org["uid"], confidence=0.8,
                        platform="lobbywatch", url=ORG_URL.format(id=org.get("id")),
                        data={"source": "lobbywatch",
                              "organisation": org.get("anzeige_name")}))
                    edges.append(EdgeResult(from_entity=org_key,
                                            to_entity=f"company_id:{org['uid']}",
                                            relation="registered_as", confidence=0.8))
            if len(rows) > MAX_TIES:
                capped += len(rows) - MAX_TIES

            # The badge. Nothing else in this framework produces this edge.
            if is_parl:
                for z in d["zutrittsberechtigung"]:
                    if z.get("parlamentarier_id") != p.get("id"):
                        continue
                    guest = pers.get(z.get("person_id"))
                    if not guest:
                        continue
                    gname = guest.get("anzeige_name") or guest.get("name")
                    findings.append(Finding(
                        entity_type="person", label=gname, confidence=0.8,
                        platform="lobbywatch", url=PROFILE_URL.format(id=p.get("id")),
                        data={"kind": "holds a Bundeshaus access badge",
                              "granted_by": name, "function": z.get("funktion"),
                              "occupation": guest.get("beruf"),
                              "description": guest.get("beschreibung_de"),
                              "source": "lobbywatch"}))
                    edges.append(EdgeResult(
                        from_entity=pkey, to_entity=f"person:{gname}",
                        relation="granted_parliament_access", confidence=0.8))

    if capped:
        errors.append(f"{NOTE_PREFIX}lobbywatch_ties: {capped} further tie(s) not "
                      f"reported (cap {MAX_TIES} per person/organisation).")
    if findings:
        undeclared = sum(1 for f in findings
                         if f.data.get("declaration") == "nicht-deklariert")
        if undeclared:
            errors.append(f"{NOTE_PREFIX}lobbywatch_ties: {undeclared} of the reported "
                          "ties are recorded as NOT declared by the parliamentarian "
                          "(`declaration: nicht-deklariert`).")
        errors.append(f"{NOTE_PREFIX}lobbywatch_ties: Lobbywatch lists CURRENT ties; "
                      "an ended tie is removed from the export rather than dated, so "
                      "this answers 'what is true now' and cannot answer a question "
                      "about an earlier year.")
    return findings, edges, errors
