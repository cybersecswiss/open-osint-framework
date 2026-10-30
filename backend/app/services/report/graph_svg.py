"""Render a case graph as a self-contained SVG for the PDF.

Why not screenshot Cytoscape? That would mean shipping a headless browser
into the API image and driving it per report — a large dependency and a new
failure mode for something that has to work offline in a customer's docker.
WeasyPrint renders inline SVG directly, so the picture is generated here in
plain Python and embedded in the HTML.

The layout is radial by design, because that is the shape these graphs
actually have: one searched selector with a corona of hits around it, and a
few second-order nodes beyond that. A force-directed layout would look
prettier and say less.

Everything is deterministic — same graph in, same picture out — so two
renders of an unchanged case produce identical PDFs.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from html import escape
from typing import Any

# Above this the picture stops being readable and becomes a grey disc. The
# omitted count is always reported to the caller so the report can say so.
MAX_NODES = 70
# Labels for everything turns the centre into a smudge. The most connected
# nodes carry the meaning, so only they get named.
MAX_LABELS = 28
_LABEL_CHARS = 24

_W, _H = 820.0, 640.0
_CX, _CY = _W / 2, _H / 2
_RING_STEP = 96.0

# Print-friendly, distinguishable in greyscale by lightness as well as hue.
_PALETTE = [
    "#1677ff", "#d46b08", "#389e0d", "#cf1322", "#531dab",
    "#08979c", "#c41d7f", "#7cb305", "#0958d9", "#ad4e00",
]
_PLACEHOLDER_COLOR = "#bfbfbf"


def _color_for(entity_type: str) -> str:
    """Stable colour per entity type — no registry to keep in sync, and the
    same type keeps its colour across cases and across reports."""
    return _PALETTE[sum(entity_type.encode()) % len(_PALETTE)]


def _truncate(text: str) -> str:
    text = text or ""
    return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1] + "…"


def build_svg(
    entities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    root_id: str | None = None,
) -> tuple[str, dict[str, int]]:
    """Return (svg_markup, stats).

    `stats` reports what was drawn and what was left out, so the section can
    print an honest caption instead of implying the picture is complete.
    """
    by_id = {str(e.get("id")): e for e in entities if e.get("id")}
    if not by_id:
        return "", {"drawn": 0, "omitted": 0, "edges": 0}

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        a, b = str(edge.get("from_entity")), str(edge.get("to_entity"))
        if a in by_id and b in by_id and a != b:
            adjacency[a].add(b)
            adjacency[b].add(a)

    degree = {nid: len(adjacency[nid]) for nid in by_id}

    # Keep the most connected nodes. Ties broken by label so the selection
    # is stable rather than dependent on dict ordering.
    ranked = sorted(
        by_id,
        key=lambda nid: (-degree.get(nid, 0), (by_id[nid].get("label") or "").lower()),
    )
    kept = set(ranked[:MAX_NODES])
    omitted = len(ranked) - len(kept)

    centre = root_id if root_id in kept else (ranked[0] if ranked else None)

    # BFS depth from the centre gives the rings. Nodes in no component with
    # the centre land on an outer ring of their own — an isolated finding is
    # still a finding and must not vanish from the picture.
    depth: dict[str, int] = {centre: 0} if centre else {}
    queue: deque[str] = deque([centre] if centre else [])
    while queue:
        node = queue.popleft()
        for neighbour in sorted(adjacency[node]):
            if neighbour in kept and neighbour not in depth:
                depth[neighbour] = depth[node] + 1
                queue.append(neighbour)
    detached = [nid for nid in kept if nid not in depth]
    max_depth = max(depth.values(), default=0)
    for nid in detached:
        depth[nid] = max_depth + 1

    rings: dict[int, list[str]] = defaultdict(list)
    for nid in kept:
        rings[depth[nid]].append(nid)
    for ring in rings.values():
        ring.sort(key=lambda nid: (-degree.get(nid, 0), (by_id[nid].get("label") or "").lower()))

    # Scale the ring spacing so the outermost ring always fits the canvas.
    depth_count = max(rings.keys(), default=0)
    step = min(_RING_STEP, (min(_W, _H) / 2 - 40) / depth_count) if depth_count else _RING_STEP

    pos: dict[str, tuple[float, float]] = {}
    for ring_index, members in rings.items():
        if ring_index == 0:
            pos[members[0]] = (_CX, _CY)
            for extra_index, nid in enumerate(members[1:], start=1):
                pos[nid] = (_CX + 18 * extra_index, _CY)
            continue
        radius = step * ring_index
        count = len(members)
        # Offset every other ring by half a slot so neighbouring rings don't
        # line up radially and overprint each other's labels.
        offset = (math.pi / count) if ring_index % 2 == 0 else 0.0
        for slot, nid in enumerate(members):
            angle = (2 * math.pi * slot / count) + offset - math.pi / 2
            pos[nid] = (_CX + radius * math.cos(angle), _CY + radius * math.sin(angle))

    labelled = set(sorted(kept, key=lambda nid: -degree.get(nid, 0))[:MAX_LABELS])

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W:.0f} {_H:.0f}" '
        f'width="100%" role="img">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    drawn_edges = 0
    for edge in edges:
        a, b = str(edge.get("from_entity")), str(edge.get("to_entity"))
        if a not in pos or b not in pos or a == b:
            continue
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#d9d9d9" stroke-width="0.8"/>'
        )
        drawn_edges += 1

    for nid in sorted(kept, key=lambda n: degree.get(n, 0)):
        x, y = pos[nid]
        ent = by_id[nid]
        virtual = bool((ent.get("data") or {}).get("virtual"))
        radius = 4.0 + min(degree.get(nid, 0), 12) * 0.9
        colour = _PLACEHOLDER_COLOR if virtual else _color_for(ent.get("entity_type") or "?")
        # Placeholders are drawn hollow: they are edge endpoints nobody
        # confirmed, and the picture should not present them as findings.
        fill = "#ffffff" if virtual else colour

        # A second ring marks a node several independent tools reported. The
        # graph scales nodes by degree, which makes the LOUDEST source lead
        # visually; the ring is the counterweight — it marks the best-supported
        # node rather than the most connected one.
        corroborators = len(ent.get("corroborated_by") or [])
        if corroborators > 1 and not virtual:
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius + 2.6:.1f}" '
                f'fill="none" stroke="{colour}" stroke-width="0.9" '
                f'stroke-opacity="0.55"/>'
            )
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill}" '
            f'stroke="{colour}" stroke-width="1.2"/>'
        )
        if nid in labelled:
            label = escape(_truncate(ent.get("label") or ""))
            parts.append(
                f'<text x="{x:.1f}" y="{y - radius - 3:.1f}" text-anchor="middle" '
                f'font-family="DejaVu Sans, sans-serif" font-size="8.5" '
                f'fill="#434343">{label}</text>'
            )

    parts.append("</svg>")
    return "".join(parts), {
        "drawn": len(kept),
        "omitted": omitted,
        "edges": drawn_edges,
    }


def legend(entities: list[dict[str, Any]], drawn_ids: set[str] | None = None) -> list[dict[str, str]]:
    """Type → colour pairs for the types actually present, most common first."""
    counts: dict[str, int] = defaultdict(int)
    for e in entities:
        if (e.get("data") or {}).get("virtual"):
            continue
        counts[e.get("entity_type") or "?"] += 1
    return [
        {"type": t, "color": _color_for(t), "count": str(n)}
        for t, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
