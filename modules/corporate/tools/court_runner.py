"""Swiss court decisions — entscheidsuche.ch (keyless).

Every other source in this framework answers "what infrastructure exists"
or "who is registered where". None of them answers the question a case file
eventually has to answer: **has a Swiss court already said something about
this person or this company?** entscheidsuche.ch is the meta-index over all
federal and cantonal Swiss court decisions, with the full PDF text, so a hit
here is not an indication — it is a signed document with a citation.

That is why findings from here rate Admiralty **A** and why the PDF URL
travels as `Finding.url`: it is the Belegstelle, in the literal sense.

⚠️  THE TRAP — READ BEFORE CHANGING THE QUERY
------------------------------------------------------------------
The obvious call is `GET /_search.php?q=<term>`. **It silently ignores the
parameter.** Measured:

    q=(leer)          → 10 000+ "hits", max_score 1.0
    q=Ransomware      → 10 000+ "hits", max_score 1.0, same first hit
    q=Phishing        → 10 000+ "hits", max_score 1.0, same first hit
    q=Xyzzyfrobnicat  → 10 000+ "hits", max_score 1.0, same first hit

Four different questions, one answer, and a constant score of 1.0 — the
signature of a match-all. A runner built on that form would have reported
"this selector appears in over 10 000 Swiss court decisions", with an edge
from the investigated selector, an entry in the findings list and a line in
the PDF report. Exactly the SHAB failure mode (see shab_runner), one
jurisdiction over.

The working form is **POST with an Elasticsearch query DSL**. And because a
silent match-all is indistinguishable from a real answer by looking at it,
this runner does not trust that fact — it re-establishes it on every run
with a NEGATIVE CONTROL (`_filter_alive`), the same discipline
`modules/base/verifier.py` applies to account checks. One extra request of
a few milliseconds buys the guarantee that a filter regression surfaces as
a refusal instead of as 10 000 fabricated hits.

A phrase hit is a MENTION, not an identity
------------------------------------------------------------------
"Hans Muster" appearing in a decision may be the subject, a cited author, a
judge, a lawyer, or a different person with the same name. The *document* is
an A-grade source; the *link between the searched name and it* is an
assertion of mention only. Hence confidence 0.6 (→ credibility 3,
"possibly true") rather than the 0.9 the document itself would deserve, plus
an explicit caveat on every finding. Overstating this would be the worse
error: an investigator can work with "possibly the same person", not with a
false certainty printed in a case file.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

ES = "https://entscheidsuche.ch/_search.php"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
MAX_RESULTS = 20
# Two fragments of ~220 chars: enough to read what the court actually wrote
# around the term, short enough that 20 hits stay a readable findings list.
FRAGMENT_SIZE = 220
FRAGMENTS = 2

# The negative control. Must be a token no Swiss court has ever printed;
# if THIS returns hits, the endpoint is answering match-all again.
_CONTROL_PHRASE = "xyzzyfrobnicat qwertzuiop nichtexistent"

# Labels for the three official languages a decision can arrive in. Every
# document carries at least `title.de`; the others are translations of the
# court's own naming, not of the decision.
_LANGS = ("de", "fr", "it")

_TAG_RE = re.compile(r"</?em>")

log = logging.getLogger("module-corporate.court")


def _pick_lang(block: Any, prefer: str | None = None) -> str:
    """Read a {de,fr,it} block, preferring the decision's own language.

    Falls back through the three languages rather than hard-coding German:
    a Geneva or Ticino decision is written in its own language and the German
    field then carries only the court's name.
    """
    if isinstance(block, str):
        return block.strip()
    if not isinstance(block, dict):
        return ""
    order = ([prefer] if prefer else []) + [x for x in _LANGS if x != prefer]
    for lang in order:
        val = block.get(lang)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _parse_date(value: Any) -> "datetime | None":
    """The decision date — a REAL source date, which is rare in this system.

    `Finding.found_at` means "when the source said it", and most runners have
    to leave it None because their source publishes no date. A court decision
    is dated by definition, so this one fills it, and the case timeline can
    place the document at the day it was handed down instead of the day we
    searched.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _excerpts(hit: dict[str, Any]) -> list[str]:
    """The highlighted passages, with the <em> markers stripped.

    Kept because "what does the decision actually say about this term" is the
    question the investigator has, and the API already paid for the answer —
    the same reasoning that put excerpts into the forum sweep.
    """
    out: list[str] = []
    for frags in (hit.get("highlight") or {}).values():
        for frag in frags or []:
            text = re.sub(r"\s+", " ", _TAG_RE.sub("", str(frag))).strip()
            if text:
                out.append(text)
    return out[:FRAGMENTS]


def _body(term: str, size: int) -> dict[str, Any]:
    """The one query shape that actually filters. See the module docstring.

    `match_phrase`, not `match`, on purpose: a searched name is a phrase.
    With `match`, "Hans Muster" would score every decision containing the
    word "Hans" — which in a corpus of Swiss judgments is a very large number
    of documents that have nothing to do with the person.
    """
    return {
        "size": size,
        # `attachment.content` is the full PDF text and can run to hundreds of
        # kilobytes per document. We never need it in full — the highlight
        # carries the part that matters — so it is excluded from _source and
        # 20 hits stay a small response instead of a multi-megabyte one.
        "_source": {"excludes": ["attachment.content"]},
        "query": {"match_phrase": {"attachment.content": term}},
        "highlight": {
            "fields": {
                "attachment.content": {
                    "fragment_size": FRAGMENT_SIZE,
                    "number_of_fragments": FRAGMENTS,
                }
            }
        },
    }


async def _search(client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    r = await client.post(ES, json=body)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise ValueError(str(payload["error"])[:200])
    return payload


async def _filter_alive(client: httpx.AsyncClient) -> bool:
    """Negative control: does the endpoint still actually filter?

    Costs one request of a few milliseconds and is the difference between
    "no Swiss court has ruled on this" and "the search silently stopped
    working". Returns False when a phrase that cannot exist still produces
    hits — at which point this runner refuses rather than emitting a corpus
    dump as findings.
    """
    try:
        payload = await _search(client, _body(_CONTROL_PHRASE, 1))
    except Exception as e:  # noqa: BLE001 — deliberately every exception
        log.info("court_decisions: negative control could not run: %s", e)
        # Could not establish it either way. Treat as NOT alive: refusing on
        # an unproven filter is the safe direction, because the failure this
        # guards against is silent and looks like a result.
        #
        # Broad on purpose. `_search` today raises only httpx.HTTPError and
        # ValueError, and catching exactly those would work — today. But this
        # guard's whole value is that it holds when something upstream
        # changes, so making it depend on the exception taxonomy of the
        # function it guards would be the one coupling it cannot afford.
        # Caught by test_court.py, which scripts a RuntimeError here.
        return False
    total = ((payload.get("hits") or {}).get("total") or {}).get("value", 0)
    if total:
        log.error("court_decisions: NEGATIVE CONTROL FAILED — the control phrase "
                  "returned %s hits; the endpoint is not filtering", total)
        return False
    return True


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "person_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["court_decisions: empty search term"]
    if len(term) < 3:
        return [], [], ["court_decisions: search term too short — a one- or "
                        "two-character phrase matches arbitrary text in a "
                        "judgment and would return noise, not findings."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    ) as client:
        if not await _filter_alive(client):
            return [], [], [
                "court_decisions: the endpoint answered a phrase that cannot "
                "exist, i.e. it is returning the whole corpus instead of "
                "search results. Refusing to emit findings that would not be "
                "about this term. (Check https://entscheidsuche.ch — the query "
                "form may have changed; see the runner docstring.)"
            ]

        try:
            payload = await _search(client, _body(term, MAX_RESULTS))
        except httpx.HTTPError as e:
            return [], [], [f"court_decisions: entscheidsuche.ch unreachable: {e}"]
        except ValueError as e:
            return [], [], [f"court_decisions: search rejected: {e}"]

    hits_block = payload.get("hits") or {}
    total_block = hits_block.get("total") or {}
    total = total_block.get("value", 0)
    relation = total_block.get("relation", "eq")
    hits = hits_block.get("hits") or []

    if not hits:
        return [], [], [f"{NOTE_PREFIX}court_decisions: no Swiss court decision "
                        f"contains the phrase '{term}'."]

    if total > len(hits):
        errors.append(
            f"{NOTE_PREFIX}court_decisions: {total}{'+' if relation == 'gte' else ''} "
            f"decisions contain this phrase; the {len(hits)} best-matching are "
            f"reported. Narrow the term to see the rest.")

    cantons: set[str] = set()
    for hit in hits:
        src = hit.get("_source") or {}
        attachment = src.get("attachment") or {}
        lang = src.get("language") or attachment.get("language")

        title = _pick_lang(src.get("title"), lang)
        doc_id = src.get("id") or hit.get("_id") or ""
        # The title is already a citation ("Bundesgericht I. Zivilrechtliche
        # Abteilung 17.08.2023 4A_206/2023"), which is what belongs on the
        # node. Fall back to the document id when a collection omits it.
        label = (title or doc_id).strip()
        if not label:
            continue
        # The entities.label column is VARCHAR(255); a few collections carry
        # long descriptive titles. Truncate visibly rather than let the write
        # fail deep in the ingest.
        if len(label) > 200:
            label = label[:197] + "…"

        pdf_url = attachment.get("content_url") or ""
        canton = (src.get("canton") or "").strip()
        if canton:
            cantons.add(canton)

        excerpts = _excerpts(hit)
        reference = src.get("reference")
        if isinstance(reference, list):
            reference = "; ".join(str(x) for x in reference if x)

        findings.append(Finding(
            entity_type="court_decision",
            label=label,
            # The PDF itself. A decision without its document is an assertion;
            # with it, it is evidence.
            url=pdf_url or None,
            # A phrase hit is a mention, not an identification — see the
            # module docstring. 0.6 → Admiralty credibility 3.
            confidence=0.6,
            # The day the court decided, not the day we looked.
            found_at=_parse_date(src.get("date")),
            data={
                "decision_date": src.get("date"),
                "canton": canton or "CH",
                "court": _pick_lang(src.get("meta"), lang) or None,
                "hierarchy": src.get("hierarchy") or [],
                "regeste": (str(reference)[:500] if reference else None),
                "abstract": (_pick_lang(src.get("abstract"), lang) or "")[:1500] or None,
                # What the decision actually says around the search term.
                "excerpts": excerpts,
                "language": lang,
                "document_id": doc_id,
                "collection": (hit.get("_index") or "").replace("entscheidsuche.v2-", ""),
                "relevance_score": round(hit.get("_score") or 0, 2),
                "register": "entscheidsuche.ch (CH court decisions)",
                # Stated on the finding itself, not only in a note: whoever
                # reads this node in six months does not read the notes.
                "caveat": ("Phrase match in the decision text. The person or "
                           "company named may be the subject, a cited author, "
                           "a party, a judge or an unrelated namesake — verify "
                           "against the linked document before relying on it."),
                "source": "entscheidsuche",
            },
        ))
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}",
            to_entity=f"court_decision:{label}",
            relation="named_in",
            confidence=0.6,
        ))

    errors.append(
        f"{NOTE_PREFIX}court_decisions: {len(findings)} decision(s) from "
        f"{len(cantons) or 1} jurisdiction(s). A hit means the phrase appears in "
        f"the text — confirm the identity against the linked PDF.")
    return findings, edges, errors
