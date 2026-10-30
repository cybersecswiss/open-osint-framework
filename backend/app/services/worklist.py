"""What in this case has never been asked about.

The question an investigator cannot answer today is "did I miss something?".
A case accumulates hundreds of findings, each of which could itself be a
selector, and nothing records which of them were ever run through the tools.
Whether a node was *found* is visible; whether it was ever *asked about* is
not — and those are different questions. A domain that turned up as a
certificate entry and was never scanned looks exactly like one that was
scanned and yielded nothing.

This module answers it from data that already exists:

  * the case's entities (from the customer agent, as everywhere else), and
  * `search_jobs` — every selector this case has been searched with.

**No new collection and no new storage.** It is a join over two things the
system already has, computed per request like the relevance ranking, for the
same reason: mark a false positive or run one more search and the answer must
change immediately.
"""
from __future__ import annotations

import re
from typing import Any

# entity_type → the query_type that entity should be searched AS.
#
# Mirrors `frontend/src/utils/pivot.ts` (TYPE_TO_QT), which decides the same
# thing for the pivot drawer. Kept in step by `test_worklist.py`, which
# asserts every target here is a type some live manifest actually accepts —
# the drift that matters is against the modules, not between the two files.
#
# Types deliberately absent: `password_fingerprint` (only pivotable when the
# cleartext was stored), `social_account` (the handle has to be parsed out of
# the label first) and every placeholder-ish type. A worklist that suggests
# selectors the tools cannot take is worse than a short one.
TYPE_TO_QUERY: dict[str, str] = {
    "email_address": "email",
    "email": "email",
    "username": "username",
    "domain": "domain",
    "dns_a": "domain", "dns_aaaa": "domain", "dns_mx": "domain",
    "dns_ns": "domain", "dns_cname": "domain",
    "ip": "ip", "ip_address": "ip",
    "phone": "phone", "phone_number": "phone",
    "btc_address": "btc_address",
    "eth_address": "eth_address",
    "telegram_channel": "tg_channel",
    "telegram_user": "tg_user",
    "onion_service": "onion_address",
    "asn": "asn",
    "cve": "cve",
    # What the CVE runner actually STORES is `vulnerability` (TYPE_MAP maps
    # cve -> vulnerability); only the pre-canonical alias was listed here, so
    # no CVE in any case has ever appeared as an open item.
    "vulnerability": "cve",
    # A look-alike of the victim's domain is a domain, and one the framework
    # found itself — without this entry none would ever be offered for a scan.
    "typosquat_domain": "domain",
    "hash": "hash",
    "url": "url",
    # Name-first types (module `corporate`). An organisation searched as a
    # plain keyword never reaches the commercial register, which is the one
    # source built for it.
    "organization": "company_name",
    "person": "person_name",
}


def _asked_key(query: str, query_type: str) -> tuple[str, str]:
    """Normalised identity of "this selector has been searched".

    Case-folded on both parts: the same domain typed in two capitalisations
    is the same search, and reporting it as an open item would send an
    investigator to repeat work they already did.
    """
    return ((query or "").strip().lower(), (query_type or "").strip().lower())


# A stored label is not always a usable selector. The CVE runner files its
# KEV flag as a second `vulnerability` node labelled `KEV:CVE-2021-44228`;
# offering that as a search proposes a query no tool can parse, and an open
# item that cannot be actioned is worse than none. Only types whose label
# shape can diverge from the selector need a gate — everything else passes.
_LABEL_OK: dict[str, "re.Pattern[str]"] = {
    "cve": re.compile(r"^CVE-\d{4}-\d{4,7}$", re.I),
}


def build(
    entities: list[dict[str, Any]],
    jobs: list[tuple[str, str]],
    tools_by_query_type: dict[str, list[str]],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Entities that could be searched and never have been, best first.

    `jobs` is (query, query_type) for every search run on this case.
    `tools_by_query_type` comes from the manifests — an entity is only worth
    suggesting if some tool would actually accept it.

    Ordering is by the relevance score already attached to each entity, so the
    suggestion list agrees with the findings list and the report instead of
    inventing a third ranking.

    Placeholder entities are included (see the comment on the `root` check):
    they are the far ends of asserted relations, and their labels are real
    selectors. They carry `from_relation=True` so a caller can mark them.
    """
    asked = {_asked_key(q, qt) for q, qt in jobs}
    out: list[dict[str, Any]] = []
    for e in entities:
        data = e.get("data") or {}
        # The search root is skipped because it is by definition the thing
        # that was already searched.
        #
        # Placeholders used to be skipped too, on the reasoning that they are
        # "the system's own bookkeeping". That reasoning was wrong, and it was
        # never checked against the data. In practice placeholder labels are
        # mail hosts, IP addresses and wallet addresses — real leads, not
        # system artefacts.
        #
        # A placeholder is simply the far end of a relation a tool asserted
        # without also reporting that end as a finding of its own: the
        # counterparty of a transaction, the host an MX record points at.
        # Those are precisely the leads worth following. Excluding them can
        # hide wallet addresses the investigator has marked relevant — the
        # one question a crypto case starts with, silently withheld.
        #
        # They are offered now, with `from_relation` set so the panel can say
        # what they are: referenced by a finding, not reported as one.
        if data.get("root"):
            continue
        if e.get("is_relevant") is False:
            continue        # already judged a false positive
        qt = TYPE_TO_QUERY.get(str(e.get("entity_type") or ""))
        if not qt:
            continue
        tools = tools_by_query_type.get(qt) or []
        if not tools:
            continue        # nothing could run it — not an open item
        label = str(e.get("label") or "")
        if not label or _asked_key(label, qt) in asked:
            continue
        shape = _LABEL_OK.get(qt)
        if shape and not shape.match(label):
            continue        # stored as a marker, not as a selector
        out.append({
            "id": str(e.get("id")),
            "label": label,
            "entity_type": e.get("entity_type"),
            "query_type": qt,
            "tool_count": len(tools),
            "tools": tools[:12],
            "relevance_score": e.get("relevance_score") or 0.0,
            "admiralty": e.get("admiralty"),
            "corroborated_by": e.get("corroborated_by") or [],
            # True when no tool reported this as a finding — it appeared as
            # the endpoint of a relation. Still a real selector, but less
            # substantiated, and the investigator should be told which it is.
            "from_relation": bool(data.get("virtual")),
        })
    out.sort(key=lambda r: (-r["relevance_score"], r["label"].lower()))
    return out[:limit]
