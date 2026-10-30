"""Rank findings so the investigator sees the twenty that matter first.

A domain search returns several hundred nodes. The system was good at
collecting them and gave no help at all deciding which ones to read, which
for time-critical work is the actual bottleneck — not the number of sources.

This is a heuristic, not a model. Four signals, each of which an analyst
would use anyway:

  1. **Corroboration** — how many independent tools reported the same thing.
     The strongest signal available, and the only one that is nearly
     impossible to fake by accident. Weighted highest.
  2. **Source reliability** — the Admiralty letter from the tool's manifest.
     A registry record outranks a scraper hit.
  3. **Centrality** — degree in the case graph. A node everything else hangs
     off is worth reading before a leaf.
  4. **Selector proximity** — hops from the node the investigator searched
     for. Distance is measured on the real graph, so a second-order hit that
     three tools confirm can still outrank a direct hit nobody confirmed.

Deliberately COMPUTED, never stored. The score is a function of the case as
it stands: mark something as a false positive, run another tool, and the
ranking must change immediately. A stored column would be stale the moment
anything else in the case moved, and nobody would know which rows were
recomputed and which were not.

Placeholders always rank last. They are edge endpoints no tool confirmed.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

# Admiralty source-reliability letter → weight. F ("cannot be judged") is not
# zero: an unrated tool still found something, and zeroing it would push every
# unrated finding below every rated one regardless of corroboration.
_RELIABILITY_WEIGHT = {"A": 1.0, "B": 0.85, "C": 0.6, "D": 0.35, "E": 0.15, "F": 0.3}

# Relative weights. Corroboration dominates on purpose — see the module
# docstring. They sum to 1.0 so a score is readable as a percentage.
_W_CORROBORATION = 0.40
_W_RELIABILITY = 0.25
_W_CENTRALITY = 0.20
_W_PROXIMITY = 0.15

# Corroboration saturates: the step from one tool to two is the meaningful
# one, from four to five is not.
_CORROBORATION_FULL = 3


def _reliability_weight(entity: dict[str, Any]) -> float:
    admiralty = entity.get("admiralty") or ""
    return _RELIABILITY_WEIGHT.get(admiralty[:1].upper(), _RELIABILITY_WEIGHT["F"])


def _distances(
    entities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    root_ids: set[str],
) -> dict[str, int]:
    """Hop count from the nearest root node, by BFS over the case graph."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        a, b = str(edge.get("from_entity")), str(edge.get("to_entity"))
        adjacency[a].add(b)
        adjacency[b].add(a)

    dist: dict[str, int] = {rid: 0 for rid in root_ids}
    queue: deque[str] = deque(root_ids)
    while queue:
        node = queue.popleft()
        for neighbour in adjacency[node]:
            if neighbour not in dist:
                dist[neighbour] = dist[node] + 1
                queue.append(neighbour)
    return dist


def score_entities(
    entities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, float]:
    """entity id → relevance score in [0, 1]."""
    if not entities:
        return {}

    degree: dict[str, int] = defaultdict(int)
    for edge in edges:
        degree[str(edge.get("from_entity"))] += 1
        degree[str(edge.get("to_entity"))] += 1
    max_degree = max(degree.values(), default=0)

    # Roots are the nodes the investigator actually searched for — the one
    # case where a placeholder is meaningful rather than noise. They carry an
    # explicit `root` flag: every virtual node has a `key`, so testing for
    # that would treat every unconfirmed edge endpoint as a search origin and
    # make proximity meaningless.
    root_ids = {
        str(e.get("id")) for e in entities
        if (e.get("data") or {}).get("root")
    }
    dist = _distances(entities, edges, root_ids) if root_ids else {}
    max_dist = max(dist.values(), default=0)

    scores: dict[str, float] = {}
    for entity in entities:
        eid = str(entity.get("id"))
        if (entity.get("data") or {}).get("virtual"):
            scores[eid] = 0.0
            continue

        corroborators = len(entity.get("corroborated_by") or [])
        corroboration = min(corroborators, _CORROBORATION_FULL) / _CORROBORATION_FULL

        centrality = (degree.get(eid, 0) / max_degree) if max_degree else 0.0

        if eid in dist and max_dist:
            proximity = 1.0 - (dist[eid] / max_dist)
        elif eid in dist:
            proximity = 1.0
        else:
            # Not connected to any root: no proximity claim either way.
            proximity = 0.0

        scores[eid] = round(
            _W_CORROBORATION * corroboration
            + _W_RELIABILITY * _reliability_weight(entity)
            + _W_CENTRALITY * centrality
            + _W_PROXIMITY * proximity,
            4,
        )
    return scores


def rank(
    entities: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Entities sorted most-relevant first, each with `relevance_score` set.

    Ties break on label so the order is stable between two renders of an
    unchanged case — an investigation product that reshuffles itself on every
    export is not one anybody can cite.
    """
    scores = score_entities(entities, edges)
    enriched = [
        {**e, "relevance_score": scores.get(str(e.get("id")), 0.0)} for e in entities
    ]
    enriched.sort(key=lambda e: (-e["relevance_score"], (e.get("label") or "").lower()))
    return enriched
