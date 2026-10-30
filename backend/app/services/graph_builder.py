"""
Turn module RunResponse payloads into Entity + Edge ORM objects.

Entities are deduplicated by their *canonical* identity (case, normalized
entity_type, clean label). Two things make dedup robust:

1. **Type normalization + label cleaning.** Runners are inconsistent —
   some emit ``entity_type="email"`` with a bare label (``foo@bar``),
   others emit the same finding with the type baked into the label
   (``label="email:foo@bar"``). Both are collapsed to one canonical node
   (``email_address`` / ``foo@bar``) via ``TYPE_MAP`` + a redundant
   ``{etype}:`` prefix strip. Without this the graph grew a *shadow*
   ``email_address`` node next to every prefixed ``email`` node (the
   "doubled email" bug).

2. **Deterministic IDs.** An entity's id is a ``uuid5`` of its canonical
   identity, so the SAME email searched twice yields the SAME id. The
   data-agent ingest is ``ON CONFLICT (id) DO NOTHING`` idempotent, so a
   re-search no longer appends a duplicate row. Edges are likewise keyed
   deterministically on ``(case, from, to, relation)``.

Edge endpoints still resolve against the by-key index built from this
batch, or against virtual placeholder entities created on the fly so the
graph stays connected even when only an edge references a node. The
lookup key keeps the raw ``etype:label`` convention the runners emit, so
edge resolution is unchanged — only the *stored* type/label/id are
canonicalized.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.entity import Edge, Entity

log = logging.getLogger("osint.graph_builder")

# Fixed namespace for deterministic entity/edge ids. Do not change — it is
# what makes the same finding across two searches collapse to one row.
_NS = uuid.UUID("6f9b1c2e-8a4d-5f3b-9e1a-0c7d2b4e6f80")

# Query types where the root node must keep the user's original spelling,
# because the runners emit the selector VERBATIM in their edge endpoints
# (`from_entity=f"keyword:{query}"`). Lowercasing the root there produces a
# key no runner ever references, so the root is stranded with zero edges
# next to the real node.
#
#   btc_address — Base58, genuinely case-significant: lowercasing
#     "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" yields a different address.
#   keyword     — free text. Searching "Hells Angels" produced TWO nodes:
#     a "hells angels" root with 0 edges and a "Hells Angels" node holding
#     all 41 hits. This hit every proper-noun search — i.e. most person and
#     organisation research — and went unnoticed because test queries were
#     lowercase ("hosting", "example.com").
#
# The rest stay lowercased: their runners normalise the value themselves
# (verified for eth_address), so differently-cased spellings still collapse
# onto one node.
# `company_name` and `person_name` join them for the same reason, found the
# same way: their root maps to `organization` / `person`, which are
# deliberately case-SENSITIVE canonical types (a name's capitalisation carries
# meaning). Lower-casing the root therefore parked "example air" next to the real
# "Example Air" with zero edges while the runners' edges all attached to the
# capitalised node — the searched selector, orphaned in its own graph.
#
# `address` joined them later, found the same way a third time — by a
# contract test rather than in production, for once. `geo_ch` emits its edge
# endpoints verbatim (`from_entity=f"address:{term}"`) and the location it
# resolves keeps the register's own capitalisation, so a lowercased root
# parked "bundesplatz 3 3011 bern" with zero edges next to the real
# "Bundesplatz 3 3011 Bern". `address` maps to the case-SENSITIVE canonical
# type `location`, which is what makes the two diverge.
_CASE_SENSITIVE_QUERY_TYPES: frozenset[str] = frozenset({
    "btc_address", "keyword", "company_name", "person_name", "address",
})


def root_key_for(query_type: str, query: str) -> str:
    """Build the by-key of the user-typed query's root node.

    Used by build_graph() and by the incremental flush in routers/search.py —
    both MUST derive it the same way, or the flush's virtual-node hold-back
    stops recognizing the root.
    """
    q = (query or "").strip()
    if query_type not in _CASE_SENSITIVE_QUERY_TYPES:
        q = q.lower()
    return f"{query_type}:{q}"

# Map a runner's raw entity_type to the canonical graph type. Keys not
# listed pass through unchanged. This is the single source of truth for
# "these two type names mean the same node".
TYPE_MAP: dict[str, str] = {
    # Legacy / cross-cutting
    "email":           "email_address",
    "email_address":   "email_address",
    "username":        "username",
    "person":          "person",
    "domain":          "domain",
    "social_account":  "social_account",
    "organization":    "organization",
    # corporate module: registers, ownership, sanctions
    "company_id":      "company_id",
    "company_name":    "organization",
    # Transport assets. A vessel and an aircraft are registered
    # assets with an owner, which is why they live in the corporate module —
    # and why they are their own node types rather than fields on an
    # organisation: `build_graph` keeps the FIRST finding per key and does
    # not merge `data`, so a ship hanging off its owner would vanish the
    # moment zefix or gleif reported that owner first.
    "vessel":          "vessel",
    "aircraft":        "aircraft",
    # Identifiers that OUTLIVE a rename. An IMO number stays with a hull for
    # life and an MSN with an airframe; the name, the flag and the tail
    # number are all changeable, and changing them is the evasion move. Kept
    # as their own nodes so two differently-named records collapse onto the
    # identifier that cannot change.
    "imo_number":      "imo_number",
    "aircraft_serial": "aircraft_serial",
    # A Swiss court decision (corporate/court_decisions). Declared rather
    # than left to the passthrough default, per the RansomLook rule below:
    # an undeclared type works by accident, and the accident ends the day
    # someone adds a near-miss spelling in another runner.
    "court_decision":  "court_decision",
    # A regulator's public warning entry (corporate/finma_warnlist). Its own
    # type on purpose: the warning must not live only as `data` on the
    # organization node, because the first finding for a key wins here and
    # zefix_registry or shab_registry usually reports the company first —
    # which would silently drop the warning. Declared, not left to the
    # passthrough default, per the rule below.
    "warning_entry":   "warning_entry",
    # The Swiss health-professional GLN (corporate/fmh_doctor_index). Its own
    # type for the same reason `imo_number` is: it is the identifier that
    # SURVIVES a change of name — which for this population is the ordinary
    # case, not the evasion move — and it is what a prescription, an
    # insurance invoice and a MedReg record all carry. Two differently-named
    # records collapse onto it.
    "gln":             "gln",
    "person_name":     "person",
    "sanction_list":   "sanction_list",
    "legal_form":      "legal_form",
    # Cybercrime-focused entity kinds
    "ip":              "ip",
    "ip_address":      "ip",
    "url":             "url",
    "hash":            "hash",
    # Shodan infra-clustering (module-infra shodan_host / favicon_pivot)
    "service":         "service",
    "vulnerability":   "vulnerability",
    "favicon_hash":    "favicon_hash",
    "dom_hash":        "dom_hash",
    # GoPlus address risk (crypto module).
    "risk_flag":       "risk_flag",
    "typosquat_domain": "typosquat_domain",
    # Image-OSINT (module-image: exif_gps / visual_geolocate)
    "image":           "image",
    "location":        "location",
    "camera":          "camera",
    # FBI-Watchdog seizure / takedown detection (module-darknet)
    "seizure_notice":  "seizure_notice",
    # dating/adult profile sweep (module-dating, off by default)
    "dating_profile":  "dating_profile",
    # Contact identifiers actors advertise on crime forums
    "jabber_id":       "jabber_id",
    "tox_id":          "tox_id",
    "session_id":      "session_id",
    # forums/pgp_lookup and darknet/onion_scrape must agree on one type, or
    # the same key becomes two nodes.
    "pgp_key":         "pgp_key",
    "pgp_fingerprint": "pgp_key",
    "btc_address":     "btc_address",
    "eth_address":     "eth_address",
    "tg_channel":      "telegram_channel",
    "telegram_channel": "telegram_channel",
    "telegram_message": "telegram_message",
    "telegram_media":  "telegram_media",
    "telegram_user":   "telegram_user",
    "telegram_ioc":    "telegram_ioc",
    "telegram_linked_channel": "telegram_linked_channel",
    "tg_user":         "telegram_user",
    "tg_geo":          "location",
    "news_article":    "news_article",
    "search_link":     "search_link",
    "onion_service":   "onion_service",
    # `onion_address` is the QUERY TYPE of onion_scrape. The root node of a
    # search is typed with the query_type, so without this mapping pivoting
    # onto a hidden service creates a second node next to the onion_service
    # node the darknet search already produced. Any query_type that denotes
    # the same thing as an entity_type belongs here.
    "onion_address":   "onion_service",
    "discord_invite":  "discord_guild",
    "keyword":         "keyword",
    "phone":           "phone",
    "first_name":      "first_name",
    "last_name":       "last_name",
    # `address` is the QUERY TYPE of corporate/geo_ch, and what it denotes is
    # exactly what four runners already emit as `location` (exif_gps,
    # visual_geolocate, shab_registry's seat, tel_search_ch). Same rule as
    # `onion_address` and `cve` above: a query_type that means the same thing
    # as an entity_type belongs here, or searching an address parks a second
    # node next to the location the graph already holds.
    # Safe to change: no runner emits entity_type "address" (checked across
    # all modules when this was added), so this only affects the root node of an
    # address search. Rows already stored keep their type.
    "address":         "location",
    "country":         "country",
    "dob":             "dob",
    "password_fingerprint": "password_fingerprint",
    "breach":          "breach",
    # Cybercrime source expansion
    "asn":             "asn",
    "ip_range":        "ip_range",
    "ransomware_group": "ransomware_group",
    "ransomware_victim": "ransomware_victim",
    # RansomLook. Declared rather than left to the passthrough
    # default: an undeclared type works by accident, and the accident ends
    # the day someone adds a near-miss spelling in another runner.
    # `threat_actor` is emitted by forums/threat_actor_check too — the two
    # MUST land on one node, which is the whole point of the alias edges.
    "threat_actor":    "threat_actor",
    # QR / DataMatrix / barcode payload read out of an image (image module).
    "machine_code":    "machine_code",
    "ransom_note":     "ransom_note",
    "darknet_market":  "darknet_market",
    # `cve` is the QUERY TYPE of cve_lookup and `vulnerability` is what both
    # it and shodan_host emit — they must collapse onto one node, or a CVE
    # searched directly sits next to the same CVE found on a host.
    "cve":             "vulnerability",
}


# Canonical types whose identity does not depend on letter case. The graph
# used to dedup on the raw label, so a runner emitting `Foo@Bar.com` created
# a second node next to `foo@bar.com` — and the code relied on every one of
# ~50 runners normalising by itself ("verified for eth_address"), which is
# not an invariant one can hold across that many independent tools.
#
# Deliberately NOT in this set:
#   btc_address — Base58, genuinely case-significant
#   keyword     — free text, and the user's spelling is the point
#   person / organization / address — human names; case carries meaning
_CASE_INSENSITIVE_TYPES: frozenset[str] = frozenset({
    "email_address", "domain", "typosquat_domain", "onion_service",
    "ip", "hash", "eth_address", "url", "username", "social_account",
    "telegram_channel", "telegram_user", "jabber_id", "favicon_hash",
    "asn", "ip_range", "vulnerability",
    # Register identifiers: a UID (CHE-418.232.486) or an LEI is a formal
    # code, not a name — case is not part of it. `person` and `organization`
    # stay out, per the note above.
    "company_id", "sanction_list",
    # Group and market names are lowercase slugs upstream ("lockbit3",
    # "vice city"); a report writing "LockBit3" must not create a twin.
    # `threat_actor` stays OUT: handles are case-significant in that
    # population, and forums/threat_actor_check already preserves them.
    "ransomware_group", "darknet_market",
})


def _identity_label(norm_type: str, label: str) -> str:
    """The label used for the deterministic id — NOT the stored one.

    Splitting identity from display is what lets two spellings of the same
    thing collapse onto one node while the graph still shows the spelling
    the source actually returned. For URLs only the scheme+host fold, since
    a path IS case-sensitive.
    """
    if norm_type not in _CASE_INSENSITIVE_TYPES:
        return label
    if norm_type == "url":
        # scheme://host is case-insensitive, everything after it is not.
        head, sep, tail = label.partition("://")
        if not sep:
            return label
        host, slash, path = tail.partition("/")
        return f"{head.lower()}://{host.lower()}{slash}{path}"
    return label.lower()


def _canon(etype: str, label: str) -> tuple[str, str, str]:
    """
    Canonicalize a (raw entity_type, raw label) pair.

    Returns ``(norm_type, clean_label, key)`` where:
      * ``norm_type`` is the canonical graph type (``TYPE_MAP``),
      * ``clean_label`` has a redundant leading ``{etype}:`` stripped
        (so ``email:foo`` → ``foo``, but ``pwfp:xyz`` on a
        ``password_fingerprint`` finding is left alone — the prefix only
        strips when it exactly matches the raw type),
      * ``key`` is ``{etype}:{clean_label}`` — the raw-type convention
        edges reference, so endpoint resolution is unchanged.
    """
    label = (label or "").strip()
    prefix = f"{etype}:"
    if label.startswith(prefix):
        label = label[len(prefix):].strip()
    norm_type = TYPE_MAP.get(etype, etype)
    key = f"{etype}:{label}"
    return norm_type, label, key


# Keys under which runners that pre-date the `url` column stashed the source
# link inside `data`. Sherlock and friends did this to work around
# build_graph dropping `Finding.url`, which is why ~52 % of stored entities
# had a link and the rest did not. Reading them here folds both conventions
# into one column instead of leaving the report to guess.
_DATA_URL_KEYS: tuple[str, ...] = (
    "url", "source_url", "link", "profile_url", "permalink", "href",
)


def _finding_url(finding: dict[str, Any]) -> str | None:
    """The citation for a finding: the explicit `url` field, else whatever
    the runner stashed in `data`. Returns None rather than an empty string
    so "no source" stays distinguishable from "empty source"."""
    direct = finding.get("url")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    data = finding.get("data") or {}
    if isinstance(data, dict):
        for key in _DATA_URL_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val.strip().startswith(("http://", "https://")):
                return val.strip()
    return None


def _parse_dt(value: Any) -> "datetime | None":
    """Coerce a runner's `found_at` into a NAIVE UTC datetime.

    Module responses arrive as parsed JSON, so this is normally an ISO
    string. Timezone-aware values are converted to UTC and stripped: the
    DB columns are naive, and handing asyncpg an aware datetime raises a
    DataError that leaves the whole job stuck on "running".
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            log.debug("unparseable found_at %r — dropping", value)
            return None
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# --- Admiralty derivation -------------------------------------------------
#
# Source reliability (A–F) is declared per tool in the module manifests and
# handed in via `reliability`. Information credibility (1–6) is derived here,
# because only the framework can see whether OTHER tools said the same thing.
#
#   1  confirmed by other sources — two or more independent tools agree
#   2  probably true              — single source, high confidence
#   3  possibly true              — single source, moderate confidence
#   4  doubtful                   — single source, low confidence
#   6  cannot be judged           — no usable confidence at all
#
# 5 ("improbable") is deliberately never assigned: nothing in the collection
# pipeline can currently justify calling a finding improbable. Emitting it
# would be a claim we cannot support, and a rating nobody can defend is worse
# than an honest gap.
_CREDIBILITY_CONFIRMED = "1"
_CREDIBILITY_UNKNOWN = "6"

# Reliability of a tool the manifest cache doesn't know. "F" is the honest
# answer — cannot be judged — not a middling guess.
_UNKNOWN_RELIABILITY = "F"


def _credibility(confidence: float | None, corroborators: int) -> str:
    """Information credibility digit for one finding."""
    if corroborators >= 2:
        return _CREDIBILITY_CONFIRMED
    if confidence is None:
        return _CREDIBILITY_UNKNOWN
    if confidence >= 0.85:
        return "2"
    if confidence >= 0.6:
        return "3"
    if confidence > 0:
        return "4"
    return _CREDIBILITY_UNKNOWN


def _best_reliability(tools: "list[str] | set[str]", reliability: dict[str, str]) -> str:
    """The best (lowest-letter) reliability among the tools that reported it.

    Best rather than worst or average: if a registry and a scraper both return
    the same value, the registry's word is what the finding is worth. A weak
    second source can only ever raise credibility, never lower reliability.
    """
    letters = [reliability.get(t, _UNKNOWN_RELIABILITY) for t in tools if t]
    letters = [x for x in letters if x in ("A", "B", "C", "D", "E", "F")]
    return min(letters) if letters else _UNKNOWN_RELIABILITY


def _entity_id(case_id: uuid.UUID, norm_type: str, label: str) -> uuid.UUID:
    """Deterministic id from canonical identity → same node across searches.

    Uses the case-folded identity label for types where case is not
    significant, so `Foo@Bar.com` and `foo@bar.com` are one node. The id
    namespace `_NS` is unchanged, so ids for already-lowercase labels (the
    overwhelming majority of existing rows) stay exactly the same.
    """
    return uuid.uuid5(_NS, f"{case_id}:{norm_type}:{_identity_label(norm_type, label)}")


def _edge_id(case_id: uuid.UUID, frm: str, to: str, relation: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{case_id}:{frm}->{to}:{relation}")


def canonical_edge(case_id: uuid.UUID, frm: str, to: str, relation: str) -> uuid.UUID:
    """Public helper: the deterministic id for an edge the SERVER derives.

    Used by the commit path when a client sends an edge without an id — a
    manually drawn link, where there is no preview to have handed one out.
    Deriving it means drawing the same link twice yields the same id, and the
    ingest's ON CONFLICT DO NOTHING collapses the repeat instead of growing a
    second identical edge.

    Note the endpoints here are the resolved entity UUIDs, whereas the search
    path keys the same formula on the raw `etype:label` endpoints the runners
    emit. That is deliberate and must stay that way: a preview hands the
    client ids built the search way, and recomputing those from UUIDs on
    commit would give the same logical edge two identities.
    """
    return _edge_id(case_id, frm, to, relation)


def canonical_entity(case_id: uuid.UUID, etype: str, label: str) -> tuple[str, str, uuid.UUID]:
    """Public helper: (canonical type, cleaned label, deterministic id).

    Used by the pivot commit path so the server derives the id from the
    content it is asked to store instead of trusting a client-supplied one.
    """
    norm_type, clean_label, _key = _canon(etype, label)
    return norm_type, clean_label, _entity_id(case_id, norm_type, clean_label)


def _virtual_entity_for(key: str, case_id: uuid.UUID, tenant: str) -> tuple[Entity, str]:
    """
    Build a placeholder entity from an edge endpoint key like
    'email:foo@bar' or 'username:johndoe'. Lets the graph stay
    connected even when only edges reference a node. Returns the entity
    plus the by-key it should be registered under (the raw key, so edges
    keep resolving).
    """
    if ":" in key:
        kind, _, raw_label = key.partition(":")
    else:
        kind, raw_label = "unknown", key
    norm_type, clean_label, canon_key = _canon(kind, raw_label)
    ent = Entity(
        id=_entity_id(case_id, norm_type, clean_label),
        case_id=case_id,
        tenant=tenant,
        entity_type=norm_type,
        label=clean_label,
        data={"virtual": True, "key": key},
        source="orchestrator",
        confidence=0.5,
    )
    # Register under the raw incoming key so the edge that referenced it
    # resolves; canon_key == key here for well-formed keys, but keep the
    # incoming key to be safe against odd label spacing.
    return ent, key


def build_graph(
    results: list[dict[str, Any]],
    case_id: uuid.UUID,
    tenant: str,
    job_id: str,
    root_query: str | None = None,
    root_query_type: str | None = None,
    reliability: dict[str, str] | None = None,
) -> tuple[list[Entity], list[Edge]]:
    """Turn module results into Entity + Edge rows.

    `reliability` maps tool name → Admiralty source reliability letter, taken
    from the module manifests (see `osint_orchestrator.tool_reliability()`).
    Omitting it is safe: every tool then rates "F" (cannot be judged).
    """
    reliability = reliability or {}
    entities: list[Entity] = []
    edges: list[Edge] = []
    by_key: dict[str, uuid.UUID] = {}
    seen_edge_ids: set[uuid.UUID] = set()

    seen_entity_ids: set[uuid.UUID] = set()

    # Which tools independently reported the same canonical entity / relation.
    # Keyed on the deterministic id, not the raw key: two spellings of one
    # address arrive under different keys but are the same thing, and that is
    # exactly the case where corroboration matters most.
    entity_tools: dict[uuid.UUID, list[str]] = {}
    edge_tools: dict[uuid.UUID, list[str]] = {}

    def _credit(bucket: dict[uuid.UUID, list[str]], oid: uuid.UUID, tool: str) -> None:
        # Synthetic producers (`<facets>`, `<orchestrator>`) are bookkeeping,
        # not sources — counting them would manufacture corroboration.
        if not tool or tool.startswith("<"):
            return
        seen = bucket.setdefault(oid, [])
        if tool not in seen:
            seen.append(tool)

    def _register(entity: Entity, key: str) -> None:
        if key in by_key:
            return
        by_key[key] = entity.id
        # Two spellings of the same thing (`Foo@Bar.com` / `foo@bar.com`)
        # arrive under different keys but resolve to the same id. Map the
        # second key onto the existing node instead of emitting a duplicate
        # row that the ingest would drop anyway — edges keep resolving
        # because the key still points at the right id.
        if entity.id in seen_entity_ids:
            return
        seen_entity_ids.add(entity.id)
        entities.append(entity)

    # First pass: real findings
    for result in results:
        tool = result.get("tool", "")
        for finding in result.get("findings", []):
            etype = finding["entity_type"]
            label = finding["label"]
            norm_type, clean_label, key = _canon(etype, label)
            # Credit the tool BEFORE the dedup skip. This is the whole point:
            # the second and third tool to report the same thing used to be
            # dropped here without a trace, discarding the strongest signal
            # the system produces.
            _credit(entity_tools, _entity_id(case_id, norm_type, clean_label), tool)
            if key in by_key:
                continue
            _register(
                Entity(
                    id=_entity_id(case_id, norm_type, clean_label),
                    case_id=case_id,
                    tenant=tenant,
                    entity_type=norm_type,
                    label=clean_label,
                    data=finding.get("data", {}),
                    source=tool,
                    confidence=finding.get("confidence", 0.8),
                    # The two fields this function used to silently discard.
                    # `url` is the citation; `observed_at` is when the source
                    # said it, as opposed to when we stored it.
                    url=_finding_url(finding),
                    observed_at=_parse_dt(finding.get("found_at")),
                ),
                key,
            )

    # Register the user-typed query as a "root" entity so it always shows in
    # the graph, even when no tool produces a finding mentioning it directly.
    # This runs AFTER the findings pass on purpose: when a tool DOES return
    # the searched selector as a real finding (e.g. blockchain_btc emitting
    # the queried address), that finding carries the payload and must win.
    # Registering the placeholder first would keep the real node out — same
    # id, so _register() and the agent's ON CONFLICT DO NOTHING would both
    # silently drop it, leaving a confidence-0.5 shell with no data.
    if root_query and root_query_type:
        root_key = root_key_for(root_query_type, root_query)
        ent, key = _virtual_entity_for(root_key, case_id, tenant)
        # Mark it. A root placeholder is NOT the same thing as an unconfirmed
        # edge endpoint: it is the selector the investigator asked about, it
        # anchors most of the graph, and consumers that drop placeholders
        # (export, ranking) must be able to tell the two apart. Without this
        # flag every virtual node looked identical, because they all carry
        # `key`.
        ent.data = {**(ent.data or {}), "root": True}
        _register(ent, key)

    # Second pass: edges (create virtual endpoints if needed)
    for result in results:
        tool = result.get("tool", "")
        for edge_data in result.get("edges", []):
            from_key = edge_data["from_entity"]
            to_key = edge_data["to_entity"]

            for k in (from_key, to_key):
                if k not in by_key:
                    ent, key = _virtual_entity_for(k, case_id, tenant)
                    _register(ent, key)

            # An edge whose two ends canonicalise onto the SAME node asserts
            # nothing, and it is not a runner bug: the two keys differ until
            # TYPE_MAP folds them. A runner emitting the conventional root
            # edge `company_name:Zarana GmbH` → `organization:Zarana GmbH`
            # has written the only thing it can write, and `company_name`
            # maps to `organization` — so every exact-name hit in the
            # corporate module (shab_registry `registered_as`,
            # finma_warnlist `matches_warning_entry`, …) drew a loop on the
            # company node. Dropped here, once, rather than asking every
            # runner to reimplement the type map it cannot see.
            if by_key[from_key] == by_key[to_key]:
                continue

            eid = _edge_id(case_id, from_key, to_key, edge_data["relation"])
            _credit(edge_tools, eid, tool)
            if eid in seen_edge_ids:
                continue
            seen_edge_ids.add(eid)
            edges.append(Edge(
                id=eid,
                case_id=case_id,
                tenant=tenant,
                from_entity=by_key[from_key],
                to_entity=by_key[to_key],
                relation_type=edge_data["relation"],
                confidence=edge_data.get("confidence", 0.8),
                source=tool,
                data={},
            ))

    # Third pass: attach corroboration and rate every node.
    #
    # This runs last because credibility depends on how many tools agreed,
    # which is only known once every result has been walked.
    for ent in entities:
        tools = entity_tools.get(ent.id, [])
        ent.corroborated_by = sorted(tools) or None
        if (ent.data or {}).get("virtual"):
            # A placeholder is an edge endpoint nobody returned as a finding.
            # Rating it would dress up an unconfirmed node as an assessed one.
            ent.admiralty = None
            continue
        letter = _best_reliability(tools or [ent.source or ""], reliability)
        ent.admiralty = letter + _credibility(
            float(ent.confidence) if ent.confidence is not None else None,
            len(tools),
        )

    for edge in edges:
        edge.corroborated_by = sorted(edge_tools.get(edge.id, [])) or None

    return entities, edges
