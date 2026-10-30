"""What the OPERATOR actually holds about one authority.

## Why this exists as code and not as a paragraph

An Auftragsverarbeitungsvertrag has to say what the processor stores. A
paragraph saying it drifts the moment somebody adds a column; a measurement
cannot. This walks the operator-side tables for one tenant and reports what
is there, classified, with live row counts — so "what do you hold about us?"
is answered with a number instead of a claim.

## The classification, and why it is three levels and not two

* **metadata** — exists because the framework has to run: ids, timestamps,
  job states, schedule. Says nothing about an investigation beyond that one
  happened.
* **case-linked** — identifies a case or an entity without describing it.
  A UUID is not a finding, but it does let the operator count and correlate.
* **content** — describes what was found or what was searched for. This is
  the category the product promises not to hold, and every row in it is
  either a deliberate exception or a defect.

Two levels would have been easier and would have hidden the interesting
part: almost everything operator-side is case-linked, and the argument is
entirely about the small content list.

## What it does NOT do

It does not read the customer's agent. That is the point — the operator has
no business enumerating a customer's case files, and a report that did so to
prove the operator holds nothing would be self-refuting.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

METADATA = "metadata"
CASE_LINKED = "case-linked"
CONTENT = "content"

# Table → column → (classification, note). Hand-written on purpose: the
# classification is a judgement about meaning, and no schema can carry it.
# A column that appears in the database but not here is reported as
# UNCLASSIFIED, which is the useful failure — it means somebody added a
# column and nobody decided what it is.
SCHEMA: dict[str, dict[str, tuple[str, str]]] = {
    "cases": {
        "id": (METADATA, "identifier"),
        "tenant": (METADATA, "which authority"),
        "case_number": (CASE_LINKED, "the authority's own reference"),
        "title": (CONTENT, "chosen by the investigator; often names the subject"),
        "description": (CONTENT, "free text"),
        "status": (METADATA, "open/closed"),
        "phase": (METADATA, "where the work stands"),
        "priority": (METADATA, "the authority's own triage"),
        "closed_at": (METADATA, ""),
        "delete_after": (METADATA, "auto-delete date from the retention setting"),
        "created_by": (CASE_LINKED, "username of the investigator"),
        "assigned_to": (CASE_LINKED, "username"),
        "created_at": (METADATA, ""),
        "updated_at": (METADATA, ""),
    },
    "search_jobs": {
        "id": (METADATA, "identifier"),
        "tenant": (METADATA, ""),
        "case_id": (CASE_LINKED, ""),
        "query": (CONTENT, "THE SELECTOR — what was searched for"),
        "query_type": (CASE_LINKED, "category of selector"),
        "modules_used": (CASE_LINKED, "which sources were asked"),
        "status": (METADATA, ""),
        "created_by": (CASE_LINKED, "username, or 'scheduler'"),
        "tool_progress": (CASE_LINKED, "per-tool state; counts, not findings"),
        "last_progress_at": (METADATA, "heartbeat for the stale-job reaper"),
        "entities_count": (CASE_LINKED, "how much was found"),
        "edges_count": (CASE_LINKED, ""),
        "started_at": (METADATA, ""),
        "completed_at": (METADATA, ""),
        "error_message": (CASE_LINKED, "tool errors; may quote a selector"),
    },
    "monitoring_configs": {
        "id": (METADATA, ""),
        "tenant": (METADATA, ""),
        "case_id": (CASE_LINKED, ""),
        "entity_id": (CASE_LINKED, "which entity is watched"),
        "query": (CONTENT, "THE SELECTOR, re-run on every tick"),
        "query_type": (CASE_LINKED, ""),
        "modules": (CASE_LINKED, ""),
        "alert_on": (METADATA, "which change types"),
        "alert_email": (CASE_LINKED, "an investigator's address"),
        "alert_webhook": (CASE_LINKED, "a customer endpoint"),
        "is_active": (METADATA, ""),
        "interval_hours": (METADATA, ""),
        "last_scan": (METADATA, ""),
        "next_scan": (METADATA, ""),
        "baseline_at": (METADATA, ""),
        "baseline_suppressed": (METADATA, "how much the first run covered"),
        "created_by": (CASE_LINKED, "username"),
        "created_at": (METADATA, ""),
    },
    "alerts": {
        "id": (METADATA, ""),
        "tenant": (METADATA, ""),
        "case_id": (CASE_LINKED, ""),
        "entity_id": (CASE_LINKED, "which entity changed"),
        "monitoring_config_id": (CASE_LINKED, ""),
        "change_type": (METADATA, "new_entity / new_account / new_edge"),
        "old_value": (CASE_LINKED, "unused — nothing writes it"),
        "new_value": (CASE_LINKED,
                      "identifiers and categories only; "
                      "labels are resolved from the agent at read time"),
        "is_read": (METADATA, ""),
        "created_at": (METADATA, ""),
    },
    "audit_log": {
        "id": (METADATA, ""),
        "tenant": (METADATA, ""),
        "action": (METADATA, "what kind of act"),
        "user_id": (CASE_LINKED, ""),
        "user_name": (CASE_LINKED, ""),
        "target_type": (METADATA, ""),
        "target_id": (CASE_LINKED, ""),
        "details": (CASE_LINKED,
                    "selectors are HMAC-fingerprinted when "
                    "AUDIT_SELECTOR_MODE=hashed, plaintext when 'full'"),
        "ip_address": (CASE_LINKED, "the investigator's address"),
        "timestamp": (METADATA, ""),
        "previous_hash": (METADATA, "chain"),
        "entry_hash": (METADATA, "chain"),
    },
    "entities": {
        "*": (CONTENT,
              "FALLBACK ONLY — filled when a push to the agent failed. "
              "Delivered and deleted every 30 min by "
              "scheduler.reconcile_local_fallback()"),
    },
    "edges": {
        "*": (CONTENT, "same fallback path as `entities`"),
    },
}


async def _count(db: AsyncSession, table: str, tenant: str) -> int | None:
    try:
        row = await db.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant = :t"), {"t": tenant})
        return int(row.scalar() or 0)
    except Exception:  # noqa: BLE001 — table gone / no tenant column
        return None


async def _actual_columns(db: AsyncSession, table: str) -> list[str]:
    row = await db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = :t"), {"t": table})
    return [r[0] for r in row.all()]


async def report(db: AsyncSession, tenant: str) -> dict[str, Any]:
    """Measured, per tenant. Safe to hand to the customer verbatim."""
    tables: list[dict] = []
    totals = {METADATA: 0, CASE_LINKED: 0, CONTENT: 0, "unclassified": 0}

    for table, columns in SCHEMA.items():
        rows = await _count(db, table, tenant)
        actual = await _actual_columns(db, table)
        entries: list[dict] = []

        if "*" in columns:
            level, note = columns["*"]
            entries.append({"column": "(all)", "classification": level, "note": note})
            totals[level] += 1
        else:
            for col in sorted(actual):
                level, note = columns.get(col, ("unclassified", ""))
                if level == "unclassified":
                    note = ("no classification recorded — add it to "
                            "services/data_exposure.SCHEMA")
                    totals["unclassified"] += 1
                else:
                    totals[level] += 1
                entries.append({"column": col, "classification": level, "note": note})
            # A classified column that no longer exists is stale bookkeeping.
            for col in sorted(set(columns) - set(actual)):
                entries.append({"column": col, "classification": "removed",
                                "note": "classified here but not in the database"})

        tables.append({"table": table, "rows_for_tenant": rows, "columns": entries})

    content = [
        {"table": t["table"], "column": c["column"], "note": c["note"]}
        for t in tables for c in t["columns"] if c["classification"] == CONTENT
    ]

    return {
        "tenant": tenant,
        "tables": tables,
        "summary": totals,
        # The short answer, and the only part most readers need.
        "content_held_operator_side": content,
        "note": (
            "Measured from the live operator database. The customer's own "
            "store is deliberately NOT inspected: enumerating a customer's "
            "case files to prove the operator does not hold them would "
            "refute itself."
        ),
    }
