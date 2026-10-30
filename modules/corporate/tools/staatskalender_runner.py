"""Staatskalender — the federal administration's own directory.

What it answers
---------------
Four questions no other tool here can:

* **Does this person actually hold the office they claim?** Name → function,
  division, department, office phone, office address, room number. A
  business-email pretext and a forged signature block both fail against the
  Federal Chancellery's own register.
* **Who works at this office?** Organisation → its people and its place in
  the departmental hierarchy.
* **Whose number is this?** An official phone number → the office it belongs
  to.
* **Which offices sit on this mail domain?** A federal office's mail domain
  (`<office>.admin.ch`) returns all of its organisational units, because the
  index matches the address of each.

Reliability A. This is the publishing authority's own record of who holds
which federal office — the same class as `shab_registry` (a register
publication) and `email_security` (a registry-published DNS record read
directly), not a compilation about third parties.

The trap this source carries, measured
--------------------------------------
`/api/search/persons?s=<term>&lang=de` filters correctly. Add the
pagination parameters the frontend does NOT send — `page` and `size` — and
the same query answers **HTTP 200 with `{"result": null, "total": 0}`**.

That is the third time this module has met the same shape of failure
(SHAB silently ignoring `query`, FINMA answering `Count: 0` to a wrong
parameter name), and it is the dangerous one: an unsupported parameter
produces *"nothing found"* rather than an error, so a runner that drifts
into sending it reports "this person holds no federal office" about
everyone, forever, while staying green.

So two things follow, both non-negotiable:

1. **Only the parameters the client itself sends are used** — `s` and
   `lang`, nothing else. The reason is written here so nobody "improves"
   the runner by adding paging.
2. **A negative control runs on EVERY call.** A random unregistrable term
   is queried alongside the real one; it must return zero. If it returns
   results, the filter has stopped biting and the runner **refuses** rather
   than reporting. A refusal that names the control is a change at the
   source, not an outage.

Further measured properties
---------------------------
* **Persons match on names only.** A phone number, an e-mail address or a
  domain returns 0 persons and N organisations — the person index does not
  cover contact fields. Contact-type queries therefore search organisations
  only, and say so.
* **Phone numbers match in stored form only.** `+41584631123` finds three
  units; `0584631123`, the same number as a Swiss national would write it,
  finds nothing. The runner tries the documented variants and reports which
  one hit, rather than presenting a formatting miss as an absence.
* **Names come in four languages** (`german`/`french`/`italian`/`english`),
  and `english` is frequently an empty string. Falling back through the
  languages avoids emitting an empty label — an unnamed node in a case file
  is worse than no node.
"""
from __future__ import annotations

import logging
import re
import secrets
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

log = logging.getLogger("module-corporate.staatskalender")

BASE = "https://www.staatskalender.admin.ch/api"
WEB = "https://www.staatskalender.admin.ch"
TIMEOUT = 30
MAX_RESULTS = 40
MAX_DETAIL = 5            # detail calls cost one request each

_CONTACT_TYPES = ("phone", "email", "domain")


def _name(node: Any, lang: str = "german") -> str:
    """Pick a non-empty label out of the four-language name object."""
    if not isinstance(node, dict):
        return str(node or "").strip()
    n = node.get("name") if isinstance(node.get("name"), dict) else node
    if not isinstance(n, dict):
        return str(n or "").strip()
    for k in (lang, "german", "french", "italian", "english"):
        v = (n.get(k) or "").strip()
        if v:
            return v
    return ""


def _abbr(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    a = node.get("nameAbbr")
    if isinstance(a, dict):
        for k in ("german", "french", "italian", "english"):
            if (a.get(k) or "").strip():
                return a[k].strip()
    return None


def _phone_variants(term: str) -> list[str]:
    """The stored form is E.164 without separators; a Swiss national form is not.

    Measured: '+4158…' (E.164) hits, '058…' (national form) does not. Both spellings are
    what an investigator actually has in front of them, so both are tried and
    the one that hit is reported.
    """
    raw = re.sub(r"[^0-9+]", "", term)
    out = [term.strip(), raw]
    if raw.startswith("0") and len(raw) > 9:
        out.append("+41" + raw[1:])
    if raw.startswith("+41"):
        out.append("0" + raw[3:])
    if raw.startswith("0041"):
        out.append("+41" + raw[4:])
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


async def _query(client: httpx.AsyncClient, kind: str, term: str) -> dict:
    # `s` and `lang` ONLY — see the module docstring. Adding `page`/`size`
    # turns every answer into a silent zero.
    r = await client.get(f"{BASE}/search/{kind}",
                         params={"s": term, "lang": "de"})
    if r.status_code != 200:
        raise RuntimeError(f"{kind} search returned HTTP {r.status_code}")
    return r.json()


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "person_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["staatskalender: empty search term"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    root = f"{query_type}:{term}"

    headers = {"User-Agent": "OOF/1.0", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers,
                                 follow_redirects=True) as client:
        # ---- negative control, every run ------------------------------
        control = f"zz{secrets.token_hex(6)}qx"
        try:
            ctrl = await _query(client, "organizations", control)
        except Exception as e:  # noqa: BLE001
            return findings, edges, [f"staatskalender: unreachable ({type(e).__name__}: {e})"]
        if (ctrl.get("total") or 0) > 0 or (ctrl.get("result") or []):
            return findings, edges, [
                "staatskalender: REFUSING to report — the negative control "
                f"('{control}', an unregistrable term) returned "
                f"{ctrl.get('total')} result(s). The search filter is no longer "
                "biting, so every answer would be unrelated to the query. This "
                "is a change at the source, not an outage."]

        # ---- what to search -------------------------------------------
        if query_type in _CONTACT_TYPES:
            kinds, terms = ["organizations"], (_phone_variants(term)
                                               if query_type == "phone" else [term])
            errors.append(f"{NOTE_PREFIX}staatskalender: the person index does not "
                          "cover phone, e-mail or domain — a contact query searches "
                          "organisational units only.")
        elif query_type == "company_name":
            kinds, terms = ["organizations"], [term]
        else:                                   # person_name / keyword
            kinds, terms = ["persons", "organizations"], [term]

        hit_term = None
        persons: list[dict] = []
        orgs: list[dict] = []
        for t in terms:
            for kind in kinds:
                try:
                    d = await _query(client, kind, t)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"staatskalender: {kind} search failed "
                                  f"({type(e).__name__})")
                    continue
                rows = d.get("result") or []
                if rows:
                    hit_term = t
                    (persons if kind == "persons" else orgs).extend(rows)
            if hit_term:
                break

        if not persons and not orgs:
            return findings, edges, errors + [
                f"{NOTE_PREFIX}staatskalender: nothing in the federal directory "
                f"matches '{term}'"
                + (f" (tried {len(terms)} spellings)" if len(terms) > 1 else "")
                + ". The register covers the FEDERAL administration only — "
                "cantonal and communal offices are not in it, so this is not a "
                "statement about the person or body."]

        if hit_term and hit_term != term:
            errors.append(f"{NOTE_PREFIX}staatskalender: '{term}' returned nothing; "
                          f"'{hit_term}' did. The directory stores numbers in one "
                          "form only — the match is the same number, differently "
                          "written.")

        # ---- persons ---------------------------------------------------
        capped = 0
        for i, p in enumerate(persons[:MAX_RESULTS]):
            label = " ".join(x for x in (p.get("givenName"), p.get("surname")) if x).strip()
            if not label:
                continue
            org, dept = p.get("organization"), p.get("department")
            org_label, dept_label = _name(org), _name(dept)
            data: dict[str, Any] = {
                "function": _name(p.get("function")),
                "organisation": org_label,
                "department": dept_label,
                "department_abbr": _abbr(dept),
                "division": _name(p.get("division")),
                "office_phone": p.get("phone"),
                "office_email": p.get("email"),
                "source": "staatskalender",
            }
            # Detail adds the office address and room — the fields that turn
            # "claims to work there" into "sits in this building".
            if i < MAX_DETAIL and p.get("id"):
                try:
                    r = await client.get(f"{BASE}/person/{p['id']}")
                    if r.status_code == 200:
                        det = r.json()
                        data.update(
                            room=det.get("roomNumber") or None,
                            building=_name(det.get("building")) or None,
                            address=det.get("address") if isinstance(det.get("address"), str)
                            else (det.get("address") or {}).get("street") if isinstance(det.get("address"), dict) else None,
                            correspondence_language=det.get("correspondenceLanguage"),
                        )
                except Exception:  # noqa: BLE001 — detail is enrichment, never fatal
                    pass

            findings.append(Finding(
                entity_type="person", label=label, confidence=0.85,
                platform="staatskalender", url=f"{WEB}/organization",
                data={k: v for k, v in data.items() if v not in (None, "")}))
            if org_label:
                findings.append(Finding(
                    entity_type="organization", label=org_label, confidence=0.85,
                    platform="staatskalender",
                    data={"department": dept_label, "source": "staatskalender"}))
                edges.append(EdgeResult(from_entity=f"person:{label}",
                                        to_entity=f"organization:{org_label}",
                                        relation="works_for", confidence=0.85))
            if org_label and dept_label and dept_label != org_label:
                edges.append(EdgeResult(from_entity=f"organization:{org_label}",
                                        to_entity=f"organization:{dept_label}",
                                        relation="part_of", confidence=0.9))
            if p.get("email"):
                findings.append(Finding(
                    entity_type="email_address", label=p["email"], confidence=0.85,
                    platform="staatskalender",
                    data={"kind": "official contact address", "source": "staatskalender"}))
                edges.append(EdgeResult(from_entity=f"person:{label}",
                                        to_entity=f"email_address:{p['email']}",
                                        relation="official_contact", confidence=0.85))
            if label.casefold() != term.casefold():
                edges.append(EdgeResult(from_entity=root, to_entity=f"person:{label}",
                                        relation="listed_in_federal_directory",
                                        confidence=0.85))
        capped += max(0, len(persons) - MAX_RESULTS)

        # ---- organisations ---------------------------------------------
        seen_orgs: set[str] = set()
        for o in orgs[:MAX_RESULTS]:
            label = _name(o)
            if not label or label in seen_orgs:
                continue
            seen_orgs.add(label)
            dept = o.get("department")
            dept_label = _name(dept)
            findings.append(Finding(
                entity_type="organization", label=label, confidence=0.9,
                platform="staatskalender",
                data={k: v for k, v in {
                    "abbreviation": _abbr(o.get("organization")) or _abbr(o),
                    "department": dept_label,
                    "department_abbr": _abbr(dept),
                    "phone": o.get("phone"),
                    "email": o.get("email"),
                    "level": "federal administration",
                    "source": "staatskalender",
                }.items() if v not in (None, "")}))
            if dept_label and dept_label != label:
                edges.append(EdgeResult(from_entity=f"organization:{label}",
                                        to_entity=f"organization:{dept_label}",
                                        relation="part_of", confidence=0.9))
            if o.get("email"):
                edges.append(EdgeResult(from_entity=f"organization:{label}",
                                        to_entity=f"email_address:{o['email']}",
                                        relation="official_contact", confidence=0.85))
            # Same rule the lobbywatch runner learned: when the match IS the
            # query, TYPE_MAP folds both keys into one node and the edge would
            # be a loop on the node under examination.
            if label.casefold() != term.casefold():
                edges.append(EdgeResult(from_entity=root,
                                        to_entity=f"organization:{label}",
                                        relation="listed_in_federal_directory",
                                        confidence=0.9))
        capped += max(0, len(orgs) - MAX_RESULTS)

    if capped:
        errors.append(f"{NOTE_PREFIX}staatskalender: {capped} further entry/entries "
                      f"not reported (cap {MAX_RESULTS} per index).")
    errors.append(f"{NOTE_PREFIX}staatskalender: negative control passed "
                  f"('{control}' → 0) — the filter was verified on this run.")
    return findings, edges, errors
