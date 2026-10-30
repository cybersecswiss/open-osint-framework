"""
Turning a monitoring rescan into Alert rows — and out of the building.

## The three breaks this closes

The alerting half of monitoring used to be missing in three independent
places:

  1. **Nothing ever constructed an `Alert` row.** `raise_alerts_for_job()`
     below is that missing writer.
  2. **`GET /entities/{id}/diff` was never built.** It exists now in
     `routers/agent_proxy.py` and shares `entity_history()` here, so the
     endpoint and the alert cannot disagree about what changed.
  3. **Nothing posted to the notification workflow.** Delivery is
     `services/notify.py`, configured by the customer in /admin → Settings.

Consequently `Alert.is_read`, the per-case alert count in `/cases/overview`,
the report's `alerts` section and `MonitoringConfig.alert_email` stop being
dead code.

## One definition of "what a run added"

`compute_additions()` is the single implementation, used by the alert
writer *and* by `GET /cases/{id}/delta`. Two implementations would be two
answers, and the one the investigator reads on screen would eventually
differ from the one that woke them at 03:00. Same argument as
`services/relevance.py` being computed in exactly one place.

## What is deliberately not alerted

**Removals.** Nothing in the pipeline records that a source stopped
returning something, so a failed tool and a takedown are indistinguishable.
Alerting on the difference would manufacture an incident out of a rate
limit. The delta endpoint states this; the alert path simply never raises
that change type.

**Placeholders.** `data.virtual` nodes exist to keep the graph connected.
Nobody asserted them, so nobody is woken for them.

**A rescan that failed.** If the job did not reach `completed`, the absence
of new findings means nothing. Raising "no changes" from a run that
errored would be a lie.

## What an Alert row may contain

**Identifiers and categories. Never the finding.** `entity_id`, `case_id`,
the change type, the entity type and the name of the tool that reported it.
Not the label, not the URL, not the value.

An alert lives in the OPERATOR's database — that is where monitoring runs
from. The finding it points at lives with the customer, and it stays there:
the list view resolves labels from the agent at read time, exactly as the
graph, the entity table and the report already do. Storing a copy here
would be the one place in the product where case content crosses back over
the boundary, and it would do so permanently and invisibly.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.monitoring import Alert, MonitoringConfig
from app.models.search import SearchJob

log = logging.getLogger("osint.alerting")

# Change types. Kept as a small closed vocabulary because the customer can
# filter on them in the notification settings, and a free-form string would
# make that filter unusable within a month.
NEW_ENTITY = "new_entity"
NEW_ACCOUNT = "new_account"
NEW_EDGE = "new_edge"

# What can actually be raised. `new_account` is a refinement of
# `new_entity`, not a separate event: a finding that is an account raises
# the account type, anything else raises the generic one, never both.
CHANGE_TYPES = (NEW_ENTITY, NEW_ACCOUNT, NEW_EDGE)

# Entity types that are "somebody has a presence here". Used to decide
# between NEW_ENTITY and NEW_ACCOUNT, because "a new profile turned up" is
# the trigger investigators actually want and "a new DOM hash turned up"
# is not.
ACCOUNT_TYPES = frozenset({
    "social_account", "dating_profile", "telegram_user", "telegram_channel",
    "discord_guild", "username", "email_address", "jabber_id", "session_id",
    "tox_id", "pgp_key",
})

# The UI offered six triggers (spec §5.7) that were written for the n8n
# workflow that was never built. Three of them cannot be produced by this
# pipeline, and offering a checkbox that silently does nothing is a defect
# in itself:
#
#   profile_changed  — needs per-entity snapshots. Nothing snapshots.
#   account_deleted  — a removal. A failed tool and a takedown are
#                      indistinguishable here; see the module docstring.
#   new_public_post  — no source reports posting events as such.
#
# Stored configs still carry the old strings, so they are translated rather
# than dropped: an existing monitor keeps working and means the nearest
# thing the system can honestly deliver. The ones that map to nothing are
# reported by /monitoring/triggers so the UI can say why the box is gone
# instead of quietly losing the user's setting.
LEGACY_TRIGGER_MAP: dict[str, str | None] = {
    "new_account_found": NEW_ACCOUNT,
    "new_connection": NEW_EDGE,
    "new_company_role": NEW_ENTITY,
    "new_public_post": NEW_ENTITY,
    "profile_changed": None,
    "account_deleted": None,
}

UNDETECTABLE_TRIGGERS = tuple(k for k, v in LEGACY_TRIGGER_MAP.items() if v is None)


def wanted_types(alert_on: list[str] | None) -> set[str]:
    """Translate a stored `alert_on` list into change types.

    Empty, or a list that maps to nothing at all, means every type — the
    same rule `enabled_modules` uses for "not restricted". A monitor whose
    only trigger was `account_deleted` would otherwise silently never fire.
    """
    raw = [t for t in (alert_on or []) if t]
    if not raw:
        return set(CHANGE_TYPES)
    out: set[str] = set()
    for t in raw:
        if t in CHANGE_TYPES:
            out.add(t)
        elif t in LEGACY_TRIGGER_MAP and LEGACY_TRIGGER_MAP[t]:
            out.add(LEGACY_TRIGGER_MAP[t])
    return out or set(CHANGE_TYPES)


def _parse_stamp(value: Any) -> datetime | None:
    """Agent timestamps arrive as ISO strings, sometimes with a Z. The DB
    columns on this side are naive UTC (see the project's datetime rule), so
    everything is normalised to naive before comparison — a tz-aware value
    compared against a naive one raises, and it would raise inside a
    background task where nobody sees it."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def split_additions(data: dict, boundary: datetime) -> tuple[list[dict], list[dict]]:
    """Rows the agent wrote at or after `boundary`.

    The discriminator is the agent's `found_at` (write time), not
    `observed_at` (what the source said). A gap-fill re-scan touches
    provenance on rows that already existed; using the source's own date
    would resurface a five-year-old breach entry as new every night.
    """
    def _new(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows or []:
            when = _parse_stamp(row.get("found_at"))
            if when is not None and when >= boundary:
                out.append(row)
        return out

    entities = [
        e for e in _new(data.get("entities") or [])
        if not (e.get("data") or {}).get("virtual")
    ]
    return entities, _new(data.get("edges") or [])


async def compute_additions(tenant: str, case_id: uuid.UUID, boundary: datetime,
                            db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """What the case gained since `boundary`, read from the sovereign store."""
    from app.services.report.generator import fetch_agent_data

    data = await fetch_agent_data(tenant, str(case_id), db)
    return split_additions(data, boundary)


async def raise_alerts_for_job(
    config_id: uuid.UUID,
    job_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Compare, persist Alert rows, notify. Returns a small summary for the log.

    Idempotent per (config, entity, change_type): re-running it for the same
    job does not double the alerts. That matters because the caller is a
    background task — a retry after a transient agent error must not turn one
    finding into two notifications.
    """
    cfg = await db.scalar(select(MonitoringConfig).where(MonitoringConfig.id == config_id))
    if cfg is None:
        return {"skipped": "config gone"}
    job = await db.scalar(select(SearchJob).where(SearchJob.id == job_id))
    if job is None:
        return {"skipped": "job gone"}

    # `partial` is the NORMAL outcome, not a degraded one: it means findings
    # were stored and at least one tool reported an error, and the large
    # majority of real-world jobs end that way. An earlier version of this
    # function required `completed` and would therefore have switched
    # alerting off almost entirely — a silent no-op, found by running it
    # rather than reading it.
    #
    # `failed` and `cancelled` are genuinely different: nothing was stored,
    # so the absence of new findings proves nothing. No alerts, and no
    # baseline either — treating a failed run as the starting state would
    # suppress the next run's real findings.
    if job.status not in ("completed", "partial"):
        log.info("alerting: job=%s ended '%s' — no alerts raised", job_id, job.status)
        return {"skipped": f"job status {job.status}"}
    job_partial = job.status == "partial"

    try:
        entities, edges = await compute_additions(cfg.tenant, cfg.case_id,
                                                  job.started_at, db)
    except Exception as exc:
        # An unreachable agent means we cannot tell what changed. Saying
        # "nothing" would be a false all-clear.
        log.warning("alerting: cannot read case %s for config %s: %s",
                    cfg.case_id, config_id, exc)
        return {"skipped": "agent unreadable", "error": str(exc)}

    # The first run establishes what is already there — see alembic 0005.
    # Everything below still runs (the count is worth recording), but no
    # Alert row is written and nothing is delivered.
    is_baseline = cfg.baseline_at is None

    wanted = wanted_types(cfg.alert_on)

    # What is already recorded for this config, so a retry is a no-op.
    existing = set(
        (str(e), t) for e, t in (await db.execute(
            select(Alert.entity_id, Alert.change_type)
            .where(Alert.monitoring_config_id == cfg.id)
        )).all()
    )

    new_rows: list[Alert] = []

    if wanted & {NEW_ENTITY, NEW_ACCOUNT}:
        for ent in entities:
            eid = str(ent.get("id") or "")
            kind = (NEW_ACCOUNT if (ent.get("entity_type") or "") in ACCOUNT_TYPES
                    else NEW_ENTITY)
            if kind not in wanted:
                continue
            if not eid or (eid, kind) in existing:
                continue
            try:
                entity_uuid = uuid.UUID(eid)
            except ValueError:
                continue
            new_rows.append(Alert(
                tenant=cfg.tenant, monitoring_config_id=cfg.id,
                entity_id=entity_uuid, case_id=cfg.case_id,
                change_type=kind,
                old_value=None,
                # Identity and provenance, not the whole row: this column is
                # read by the report and by a webhook payload, and copying a
                # full `data` blob in would put arbitrary findings into both.
                # ⚠️ IDENTIFIERS AND CATEGORIES ONLY — never the finding.
                #
                # The first version of this stored
                # `label`, `url`, `confidence` and `admiralty`. `label` IS
                # the finding — an address, a handle, a leak-site entry —
                # and `url` is where it was found. Writing them here put
                # case content into the OPERATOR's database, in a product
                # whose entire promise is that findings live with the
                # customer. It was a regression introduced by the alert
                # chain, not a pre-existing condition: these columns had
                # been dead before.
                #
                # `entity_type` is a category and `source` is the name of a
                # tool the operator ran anyway. Everything else is resolved
                # at READ time from the agent (routers/agent_proxy.py), the
                # same way the graph, the entity list and the report already
                # work. The alert list looks identical and the operator's
                # store holds nothing it should not.
                new_value={
                    "entity_type": ent.get("entity_type"),
                    "source": ent.get("source"),
                },
            ))
            existing.add((eid, kind))

    if NEW_EDGE in wanted:
        for edge in edges:
            # An edge is attributed to its target: that is the thing the
            # investigator was watching when they said "tell me if this
            # entity gains a connection".
            target = str(edge.get("to_entity") or "")
            if not target or (target, NEW_EDGE) in existing:
                continue
            try:
                entity_uuid = uuid.UUID(target)
            except ValueError:
                continue
            new_rows.append(Alert(
                tenant=cfg.tenant, monitoring_config_id=cfg.id,
                entity_id=entity_uuid, case_id=cfg.case_id,
                change_type=NEW_EDGE, old_value=None,
                # Same rule. from/to are ids, `relation` is a type name
                # ("resolves_to"), `source` is the tool. No labels.
                new_value={
                    "from_entity": str(edge.get("from_entity") or ""),
                    "to_entity": target,
                    "relation": edge.get("relation") or edge.get("label"),
                    "source": edge.get("source"),
                },
            ))
            existing.add((target, NEW_EDGE))

    if is_baseline:
        cfg.baseline_at = job.completed_at or datetime.utcnow()
        cfg.baseline_suppressed = len(new_rows)
        await db.commit()
        log.info("alerting: config=%s job=%s — BASELINE, %d finding(s) recorded "
                 "as the starting state, no alerts raised%s",
                 config_id, job_id, len(new_rows),
                 " (run was partial — the baseline may be incomplete)" if job_partial else "")
        return {"alerts": 0, "baseline": len(new_rows), "partial": job_partial}

    if not new_rows:
        log.info("alerting: config=%s job=%s — nothing new", config_id, job_id)
        return {"alerts": 0}

    for row in new_rows:
        db.add(row)
    await db.commit()
    for row in new_rows:
        await db.refresh(row)

    case = await db.scalar(select(Case).where(Case.id == cfg.case_id))
    payload = [
        {
            "id": str(r.id), "entity_id": str(r.entity_id), "case_id": str(r.case_id),
            "change_type": r.change_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in new_rows
    ]

    # Delivery is best-effort and must never roll back the rows: an alert
    # that exists but was not mailed is recoverable (it is on the dashboard);
    # an alert that was mailed but not stored is not.
    delivered: list[dict] = []
    try:
        from app.services import notify

        results = await notify.deliver_alerts(
            cfg.tenant, payload,
            case_title=(case.title if case else None),
            recipient=cfg.alert_email,
            webhook_override=cfg.alert_webhook,
            # A partial run means some tools failed. Saying so turns "here
            # is what changed" into "here is what changed, and this list
            # may be short" — the difference between a report and a claim.
            partial=job_partial,
        )
        delivered = [r.as_dict() for r in results]
    except Exception:
        log.exception("alerting: notification dispatch failed for config=%s", config_id)

    log.info("alerting: config=%s job=%s — %d alert(s), delivery=%s",
             config_id, job_id, len(new_rows), delivered or "not configured")
    return {"alerts": len(new_rows), "delivery": delivered}


async def entity_history(tenant: str, case_id: uuid.UUID, entity_id: uuid.UUID,
                         db: AsyncSession) -> dict:
    """Everything recorded about how one entity came to look the way it does.

    This is what `GET /entities/{id}/diff` returns — the endpoint
    `change-detection-alert` has been calling since it was written, and which
    answered 404 the whole time.

    Honest about its limit: the framework does not snapshot entities, so this
    is not a field-by-field diff between two points in time. What it *can*
    reconstruct is real and is what an investigator asks for — when the row
    was first written, which tools have asserted it since, which alerts
    reference it, and which searches could have touched it. Inventing a
    before/after out of data that was never captured would be worse than
    saying what is actually known.
    """
    from app.services.report.generator import fetch_agent_data

    data = await fetch_agent_data(tenant, str(case_id), db)
    entity = next((e for e in (data.get("entities") or [])
                   if str(e.get("id")) == str(entity_id)), None)
    if entity is None:
        return {}

    edges = [
        e for e in (data.get("edges") or [])
        if str(e.get("from_entity")) == str(entity_id)
        or str(e.get("to_entity")) == str(entity_id)
    ]

    alerts = (await db.execute(
        select(Alert)
        .where(Alert.entity_id == entity_id, Alert.tenant == tenant)
        .order_by(Alert.created_at.desc())
    )).scalars().all()

    jobs = (await db.execute(
        select(SearchJob)
        .where(SearchJob.case_id == case_id, SearchJob.tenant == tenant)
        .order_by(SearchJob.started_at.desc()).limit(20)
    )).scalars().all()

    first_seen = _parse_stamp(entity.get("found_at"))
    observed = _parse_stamp(entity.get("observed_at"))

    return {
        "entity": {
            "id": str(entity.get("id")),
            "entity_type": entity.get("entity_type"),
            "label": entity.get("label"),
            "url": entity.get("url"),
            "source": entity.get("source"),
            "confidence": entity.get("confidence"),
            "admiralty": entity.get("admiralty"),
            "corroborated_by": entity.get("corroborated_by") or [],
            "is_relevant": entity.get("is_relevant"),
            "notes": entity.get("notes"),
        },
        "first_stored_at": first_seen.isoformat() if first_seen else None,
        "source_observed_at": observed.isoformat() if observed else None,
        # The strongest change signal the system actually produces: each
        # additional tool in this list is an independent confirmation that
        # arrived at some point after the first.
        "corroborations": len(entity.get("corroborated_by") or []),
        "edges": [
            {"from_entity": str(e.get("from_entity")), "to_entity": str(e.get("to_entity")),
             "relation": e.get("relation") or e.get("label"), "source": e.get("source"),
             "found_at": e.get("found_at")}
            for e in edges
        ],
        "alerts": [
            {"id": str(a.id), "change_type": a.change_type,
             "new_value": a.new_value, "old_value": a.old_value,
             "is_read": a.is_read,
             "created_at": a.created_at.isoformat() if a.created_at else None}
            for a in alerts
        ],
        "searches": [
            {"job_id": str(j.id), "query": j.query, "query_type": j.query_type,
             "status": j.status,
             "started_at": j.started_at.isoformat() if j.started_at else None}
            for j in jobs
        ],
        "note": ("The framework does not snapshot entities, so this is a "
                 "provenance history rather than a field-level diff. What is "
                 "shown is recorded fact; a before/after would be invented."),
    }
