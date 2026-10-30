"""Swiss addresses, buildings and parcels — api3.geo.admin.ch (keyless).

The framework already produces `location` nodes: `exif_gps` from a seized
photograph, `visual_geolocate` from an image, `tg_geo` from a Telegram geo
sweep, and the registered seat out of `shab_registry` / `tel_search_ch`.
Until now nothing could *resolve* them. A pair of coordinates sat in the
graph as a pair of coordinates, and a registered seat sat there as a town
name — neither could be placed on the map, tied to a building, or given a
canton.

This closes that. It runs in both directions:

* **forward** — an address or place ("Bundesplatz 3 Bern", "Winterthur")
  becomes coordinates, postcode, municipality, BFS number and canton;
* **reverse** — a coordinate pair becomes the nearest registered building
  from the federal building and dwelling register (GWR), with its E-GRID
  parcel identifier, municipality and canton.

Both are official federal geodata, hence Admiralty **A** — but see the
honesty note on the reverse direction below, which is why its findings carry
a *lower confidence* than the letter alone would suggest.

⚠️  THE TRAP — the municipality layer is a TIME SERIES
------------------------------------------------------------------
`ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill` does not contain the
current municipalities. It contains **every** municipal boundary since 1850,
and the API returns them oldest-first. Measured at the Bundesplatz in Bern:

    177 features returned
    176 historical (jahr 1850 … 2025, is_current_jahr = false)
      1 current    (jahr 2026, is_current_jahr = true)  ← the 177th

Taking `results[0]`, which is the obvious thing to do, answers with the
municipal boundary **as it stood in 1850**. It would have been a plausible
answer — the right canton, usually the right name — and wrong in exactly the
cases where it matters, namely the hundreds of Swiss municipalities that have
merged since. `_current_only()` exists for that and must not be removed.

Honesty about the reverse direction
------------------------------------------------------------------
A coordinate is a point, not an address. The reverse lookup returns the
nearest registered building within `REVERSE_TOLERANCE_M`, which is an
*inference*, not a record: a GPS fix from a photograph carries its own error,
and in a dense quarter the nearest building can be the one next door.
Measured: 46.9468,7.4442 (Bundesplatz) resolves to "Gurtengasse 3", roughly
50 m away and a different building than the one the coordinate names.

So reverse findings get confidence 0.65 and say so in `data.caveat`, while an
exact forward address match gets 0.9. Reporting a neighbour's address as the
subject's, in a case file, is the error this guards against.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from urllib.parse import quote

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

BASE = "https://api3.geo.admin.ch/rest/services"
MAP = "https://map.geo.admin.ch/?swisssearch={q}"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 30
MAX_RESULTS = 8

# Metres around a coordinate in which a registered building counts as "the"
# building. Wide enough to survive ordinary GPS error, narrow enough that the
# answer stays in the right block.
REVERSE_TOLERANCE_M = 50

# The federal building and dwelling register: street, number, postcode,
# municipality, canton, E-GRID parcel, building id.
LAYER_GWR = "ch.bfs.gebaeude_wohnungs_register"
# Fallback when a coordinate has no building near it (a field, a lake, a
# pass). Historical time series — see the module docstring.
LAYER_GEMEINDE = "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"

# Switzerland plus Liechtenstein, generously. Outside this the service has no
# data at all, and "no result" would read as "this place does not exist"
# rather than "this service does not cover it".
CH_BBOX = (45.7, 47.9, 5.8, 10.6)   # lat_min, lat_max, lon_min, lon_max

# "46.9468,7.4442" / "46.9468 7.4442" / "46.9468; 7.4442"
_COORD_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
# Strips ANY markup the search service wraps its labels in, not just <b>.
# It also emits <i> for gazetteer entries ("<i>Landesgrenzstein</i> 99"),
# which leaked into the node label in the first version.
_TAG_RE = re.compile(r"<[^>]+>")
# A token worth matching on: letters only, long enough not to be a filler
# word. Numbers are excluded on purpose — see `_is_related`.
_TOKEN_RE = re.compile(r"[^\W\d_]{4,}", re.UNICODE)

log = logging.getLogger("module-corporate.geo")


def parse_coords(term: str) -> "tuple[float, float] | None":
    """(lat, lon) if the term is a coordinate pair, else None.

    Swiss coordinates are always lat < lon (roughly 46/8), so a swapped pair
    is detectable and silently corrected rather than looked up at a point in
    the Indian Ocean.
    """
    m = _COORD_RE.match(term or "")
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    lat, lon = (a, b)
    if not (CH_BBOX[0] <= lat <= CH_BBOX[1]) and (CH_BBOX[0] <= b <= CH_BBOX[1]):
        lat, lon = b, a          # the pair was given lon,lat
    return lat, lon


def in_switzerland(lat: float, lon: float) -> bool:
    return (CH_BBOX[0] <= lat <= CH_BBOX[1]) and (CH_BBOX[2] <= lon <= CH_BBOX[3])


def _current_only(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the historical rows of a time-series layer. See the docstring.

    A layer without the flag is left untouched: absence of the field means
    "not a time series", not "all historical".
    """
    out = []
    for r in results:
        attrs = r.get("attributes") or {}
        if "is_current_jahr" in attrs and not attrs.get("is_current_jahr"):
            continue
        out.append(r)
    return out


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", str(text or ""))).strip()


def _fold(text: str) -> str:
    """Lowercase and strip diacritics, so "Zürich" and "Zurich" compare equal."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _expand_umlauts(token: str) -> str:
    """"zuerich" → "zurich". The transliteration a German keyboard produces.

    Applied only to the QUERY token when testing for a match, never to stored
    text: it can add a match, never remove one, so a word like "bauer" that
    the rule would mangle still matches through its unexpanded form.
    """
    for a, b in (("ae", "a"), ("oe", "o"), ("ue", "u")):
        token = token.replace(a, b)
    return token


def _is_related(term: str, detail: str, label: str) -> bool:
    """Does this result actually have to do with what was asked?

    ⚠️  The reason this exists. SearchServer falls back to partial matching,
    and a query whose street does not exist is answered by whatever else in
    it matches — usually the house number. Measured:

        "Zzqxvwstrasse 99"  →  7 results, all "Landesgrenzstein 99",
                               scattered across VD, JU and ZH

    Those came back through the same code path as a real address and would
    have been emitted at confidence 0.9: seven plausible Swiss locations, in
    a case file, for an address that does not exist. A tool that answers a
    nonsense address with confident coordinates is worse than one that
    answers nothing, because nothing about the output says it guessed.

    Rule: at least one alphabetic token of the query (4+ characters) must
    appear in the result. A query made only of numbers cannot be checked this
    way and is let through — the caller lowers confidence for that case.
    """
    haystack = _fold(f"{detail} {label}")
    tokens = _TOKEN_RE.findall(_fold(term))
    if not tokens:
        return True
    return any(t in haystack or _expand_umlauts(t) in haystack for t in tokens)


# "Winterthur (ZH) - Wiesendangen…" — gazetteer entries carry the canton in
# the label rather than at the end of `detail`.
_CANTON_IN_LABEL_RE = re.compile(r"\(([A-Z]{2})\)")

_CANTONS = {
    "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU",
    "NE", "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS",
    "ZG", "ZH",
}


def _canton_from_label(label: str) -> str:
    """Canton code out of a gazetteer label, validated against the real 26.

    Validated rather than trusted: the pattern also matches things like
    "(AB)", and an invented canton code in a case file is a fact nobody can
    check.
    """
    for code in _CANTON_IN_LABEL_RE.findall(label or ""):
        if code in _CANTONS:
            return code
    return ""


def _canton_from_detail(detail: str) -> str:
    """SearchServer packs the canton into the end of `detail`:
    "bundesplatz 3 3011 bern 351 bern ch be" → "BE".
    Read it from the tail rather than guessing from the town name."""
    parts = _clean(detail).lower().split()
    if len(parts) >= 2 and parts[-2] == "ch" and len(parts[-1]) == 2:
        return parts[-1].upper()
    return ""


async def _identify(client: httpx.AsyncClient, lat: float, lon: float,
                    layer: str, tolerance: int) -> list[dict[str, Any]]:
    """MapServer/identify at a point.

    `mapExtent` and `imageDisplay` are NOT optional even though nothing here
    renders an image: the service derives the pixel-to-metre ratio for
    `tolerance` from them and answers with an empty result set when they are
    missing. Measured — the first version of this call returned 0 features
    for a coordinate that plainly has a building on it.
    """
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "layers": f"all:{layer}",
        "sr": "4326",
        "tolerance": str(tolerance),
        "returnGeometry": "false",
        "imageDisplay": "100,100,96",
        "mapExtent": f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}",
    }
    r = await client.get(f"{BASE}/api/MapServer/identify", params=params)
    r.raise_for_status()
    return (r.json() or {}).get("results") or []


async def _reverse(client: httpx.AsyncClient, lat: float, lon: float,
                   ) -> tuple[list[Finding], list[EdgeResult], list[str], str]:
    """Coordinate → nearest registered building, else the municipality."""
    findings: list[Finding] = []
    notes: list[str] = []

    buildings = await _identify(client, lat, lon, LAYER_GWR, REVERSE_TOLERANCE_M)
    if buildings:
        a = buildings[0].get("attributes") or {}
        street = _clean(a.get("strname_deinr"))
        town = _clean(a.get("ggdename"))
        # "3011/301100" — the first part is the postcode, the second the
        # six-digit internal code. Only the first belongs in an address.
        postcode = _clean(a.get("plz_plz6")).split("/")[0]
        label = " ".join(x for x in (street, postcode, town) if x) or town
        findings.append(Finding(
            entity_type="location",
            label=label,
            url=MAP.format(q=quote(label)),
            # An inference, not a record — see the module docstring.
            confidence=0.65,
            data={
                "lat": lat, "lon": lon,
                "street": street or None,
                "postcode": postcode or None,
                "municipality": town or None,
                "bfs_number": a.get("ggdenr"),
                "canton": _clean(a.get("gdekt")) or None,
                # The federal parcel identifier. A land-register search
                # starts from this, and nothing else here can produce it.
                "egrid": _clean(a.get("egrid")) or None,
                "parcel": _clean(a.get("lparz")) or None,
                "building_id_egid": _clean(a.get("egid")) or None,
                "building_year": a.get("gbauj") or None,
                "register": "GWR — federal building and dwelling register",
                "direction": "reverse (coordinate → building)",
                "caveat": (f"Nearest registered building within "
                           f"{REVERSE_TOLERANCE_M} m of the coordinate. A GPS "
                           f"fix carries its own error and in a dense quarter "
                           f"the nearest building can be the neighbouring one "
                           f"— treat as a lead, not as the address."),
                "source": "geo.admin.ch",
            },
        ))
        return findings, [], notes, label

    # No building nearby. Fall back to which municipality the point is in —
    # coarser, but still an answer, and for a coordinate in open country it is
    # the only true one.
    areas = _current_only(await _identify(client, lat, lon, LAYER_GEMEINDE, 0))
    if not areas:
        return [], [], [f"{NOTE_PREFIX}geo_ch: the coordinate {lat},{lon} lies "
                        f"inside the Swiss coverage area but matches neither a "
                        f"registered building within {REVERSE_TOLERANCE_M} m nor "
                        f"a municipality."], ""
    a = areas[0].get("attributes") or {}
    label = _clean(a.get("gemname"))
    findings.append(Finding(
        entity_type="location", label=label,
        url=MAP.format(q=quote(label)), confidence=0.6,
        data={
            "lat": lat, "lon": lon,
            "municipality": label or None,
            "canton": _clean(a.get("kanton")) or None,
            "bfs_number": a.get("gde_nr"),
            "boundary_year": a.get("jahr"),
            "register": "swissBOUNDARIES3D (current municipal boundaries)",
            "direction": "reverse (coordinate → municipality)",
            "caveat": ("No registered building within "
                       f"{REVERSE_TOLERANCE_M} m — this is the municipality "
                       "the point falls in, not an address."),
            "source": "geo.admin.ch",
        },
    ))
    notes.append(f"{NOTE_PREFIX}geo_ch: no building within "
                 f"{REVERSE_TOLERANCE_M} m; answered with the municipality.")
    return findings, [], notes, label


async def _forward(client: httpx.AsyncClient, term: str,
                   ) -> tuple[list[Finding], list[str]]:
    """Address or place name → coordinates, municipality, canton."""
    r = await client.get(f"{BASE}/api/SearchServer", params={
        "searchText": term, "type": "locations", "sr": "4326",
        "limit": str(MAX_RESULTS),
    })
    r.raise_for_status()
    results = (r.json() or {}).get("results") or []
    if not results:
        return [], [f"{NOTE_PREFIX}geo_ch: no Swiss address or place matches "
                    f"'{term}'."]

    findings: list[Finding] = []
    seen: set[str] = set()
    dropped = 0
    # A query with no word in it ("99", "3011") cannot be checked by
    # `_is_related`, so everything it returns is let through. Measured: "99"
    # answers with border markers in VD, JU and ZH — real entries, but the
    # query did not identify a place, and 0.9 would say it had.
    unverifiable = not _TOKEN_RE.search(_fold(term))
    for item in results[:MAX_RESULTS]:
        attrs = item.get("attrs") or {}
        label = _clean(attrs.get("label"))
        if not label or label.lower() in seen:
            continue
        detail = _clean(attrs.get("detail"))
        # The partial-match guard — see `_is_related`.
        if not _is_related(term, detail, label):
            dropped += 1
            continue
        seen.add(label.lower())
        try:
            lat, lon = float(attrs["lat"]), float(attrs["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        # An exact street address is a register entry; a place name is a
        # gazetteer label covering an area. Rating them alike would overstate
        # the second.
        exact = bool(attrs.get("num")) and bool(re.search(r"\d", label))
        confidence = 0.9 if exact else 0.8
        if unverifiable:
            confidence = 0.5
        findings.append(Finding(
            entity_type="location",
            label=label,
            url=MAP.format(q=quote(label)),
            confidence=confidence,
            data={
                "lat": lat, "lon": lon,
                "canton": (_canton_from_detail(detail)
                           or _canton_from_label(label) or None),
                "detail": detail or None,
                "kind": "address" if exact else "place",
                "register": "swisstopo / geo.admin.ch location search",
                "direction": "forward (address → coordinate)",
                "caveat": (("The search term contains no name, only digits, so "
                            "the result could not be checked against it — this "
                            "is whatever the service matched on the number.")
                           if unverifiable else None),
                "source": "geo.admin.ch",
            },
        ))

    notes: list[str] = []
    if dropped:
        # Reported, not silent: an investigator who searched an address and
        # gets nothing back deserves to know the service DID answer, and that
        # the answers were about something else.
        notes.append(f"{NOTE_PREFIX}geo_ch: {dropped} result(s) discarded — the "
                     f"search service answered with entries sharing only a "
                     f"house number or fragment with '{term}', not the name.")
    if not findings:
        notes.append(f"{NOTE_PREFIX}geo_ch: no Swiss address or place matches "
                     f"'{term}'.")
    return findings, notes


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "address",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["geo_ch: empty search term"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    coords = parse_coords(term)

    if coords and not in_switzerland(*coords):
        # Say which it is. "No result" for a Berlin coordinate would read as
        # "this place does not exist" rather than "this service is Swiss".
        return [], [], [f"{NOTE_PREFIX}geo_ch: {coords[0]},{coords[1]} lies "
                        f"outside Switzerland — geo.admin.ch is the Swiss "
                        f"federal geoportal and holds no data there."]

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        try:
            if coords:
                findings, _e, notes, _label = await _reverse(client, *coords)
                errors.extend(notes)
                relation = "nearest_address"
            else:
                findings, notes = await _forward(client, term)
                errors.extend(notes)
                relation = "geocoded_to"
        except httpx.HTTPError as e:
            return [], [], [f"geo_ch: geo.admin.ch unreachable: {e}"]
        except ValueError as e:
            return [], [], [f"geo_ch: unreadable response from geo.admin.ch: {e}"]

    for f in findings:
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}",
            to_entity=f"location:{f.label}",
            relation=relation,
            confidence=float(f.confidence),
        ))

    if findings and not coords and len(findings) > 1:
        errors.append(f"{NOTE_PREFIX}geo_ch: {len(findings)} Swiss addresses or "
                      f"places match '{term}'. Add the postcode or the "
                      f"municipality to narrow it to one.")
    return findings, edges, errors
