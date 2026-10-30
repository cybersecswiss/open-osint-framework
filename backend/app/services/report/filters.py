"""Shared triage rules for report sections.

Every section that shows entities must agree on two questions, or the same
report contradicts itself: *what counts as a finding* and *what counts as
relevant*. Both answers live here.

**Placeholders.** `graph_builder` invents an entity whenever an edge points
at something no tool has returned as a finding yet (`data.virtual = true`).
They are needed to keep the graph connected, but they are not knowledge —
nobody asserted them. Roughly one node in seven was one of these, and they
sat in the entity table and the totals as equals next to real hits.

**Relevance.** `is_relevant` is a three-state field:

    True   — the investigator marked it as relevant
    False  — marked as a false positive
    None   — never triaged

A report over a triaged case should be the case file, not the raw haul. But
a report over an untriaged case must not come out empty. So: if anything in
the case was marked relevant, the report shows exactly that selection;
otherwise it shows everything that isn't a known false positive. Either way
the suppressed count is stated, because a filtered report that doesn't say
it is filtered is worse than an unfiltered one.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any


def is_placeholder(entity: dict[str, Any]) -> bool:
    """True for a graph-connectivity stub that no tool ever confirmed."""
    return bool((entity.get("data") or {}).get("virtual"))


def split_placeholders(
    entities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(real findings, placeholders)."""
    real, virtual = [], []
    for e in entities:
        (virtual if is_placeholder(e) else real).append(e)
    return real, virtual


# What the report was asked to show. Set once per report by the
# generator, read here, so every section applies the same rule:
#   "relevant" — only findings marked relevant (an explicit extract)
#   "all"      — every real finding not marked as a false positive
#   "auto"     — the rule before the explicit choice existed: relevant ones
#                if any are marked, otherwise the unassessed ones. It hid
#                unmarked findings from a full report without anyone having
#                asked for an extract; kept only for callers that set nothing.
report_scope: ContextVar[str] = ContextVar("report_scope", default="auto")


def triage(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply both rules once and hand every section the same answer.

    Returns a dict with:
      shown        — the entities the report should list
      placeholders — connectivity stubs, excluded from `shown`
      rejected     — explicitly marked as false positives
      untriaged    — real, never assessed (suppressed only when a
                     relevant-selection exists)
      filtered     — True when a relevant-selection drove the choice
      total_real   — placeholders excluded
    """
    real, placeholders = split_placeholders(entities)
    relevant = [e for e in real if e.get("is_relevant") is True]
    rejected = [e for e in real if e.get("is_relevant") is False]
    untriaged = [e for e in real if e.get("is_relevant") is None]

    scope = report_scope.get()
    if scope == "relevant":
        shown, filtered = relevant, True
    elif scope == "all":
        shown, filtered = relevant + untriaged, False
    elif relevant:
        shown = relevant
        filtered = True
    else:
        shown = untriaged
        filtered = False

    return {
        "shown": shown,
        "placeholders": placeholders,
        "rejected": rejected,
        "untriaged": untriaged,
        "relevant": relevant,
        "filtered": filtered,
        "total_real": len(real),
        "suppressed": len(real) - len(shown),
    }


def entity_index(entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """id → entity, for resolving edge endpoints to labels."""
    return {str(e.get("id")): e for e in entities if e.get("id")}
