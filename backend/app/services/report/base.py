"""
Section registry. A section is a plugin that contributes one part of
the report (cover page, summary, entity table, etc.).

Module-level invariant: every section file must call
`@register_section(...)` exactly once. The decorator stores the
builder in `_REGISTRY` keyed by section name. The generator iterates
this registry in `order` ascending.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------
# Time. One helper, because a case file may not contain two answers to
# "when did this happen".
#
# In a generated report, nearly all timestamps used to lack a zone marker
# and all of them were UTC — while the app itself
# renders Europe/Zurich. So the same event read 13:02 in the PDF annex and
# 15:02 on screen, with nothing in either document to explain the gap. For a
# report that gets filed as an annex that is not cosmetic.
#
# Two decisions:
#
# * **Local time, not UTC.** The people reading this work in Switzerland and
#   testify about Swiss timestamps. Matching the UI also means the number an
#   investigator remembers from the screen is the number in the document.
# * **The zone is stated once, on the cover, not on every row.** 73 repeats
#   of "CEST" would be noise, and noise is how a reader stops reading. The
#   cover carries the sentence; every table below it inherits it.
#
# DB columns are naive UTC (asyncpg rejects tz-aware writes here), so a naive
# value is *defined* as UTC rather than guessed at.
# --------------------------------------------------------------------------

REPORT_TZ = ZoneInfo(os.environ.get("REPORT_TIMEZONE", "Europe/Zurich"))


def _as_aware(value: Any) -> Optional[datetime]:
    """Coerce a datetime or ISO string to an aware datetime, or None."""
    if not value:
        return None
    dt = value
    if not isinstance(dt, datetime):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    # Naive means UTC here — see the module note above.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def fmt_dt(value: Any, *, dash: str = "—") -> str:
    """`03.08.2026 15:02` in the report timezone. Swiss format, minute
    precision — seconds are noise in a case file."""
    dt = _as_aware(value)
    if dt is None:
        # Not parseable: show what we were given rather than inventing a
        # dash. An unreadable stamp is information; a dash hides it.
        return str(value)[:19] if value else dash
    return dt.astimezone(REPORT_TZ).strftime("%d.%m.%Y %H:%M")


def fmt_dt_zoned(value: Any) -> str:
    """Same, plus the zone abbreviation. For the two places that stand
    alone — the generation stamp and the cover's timezone note."""
    dt = _as_aware(value)
    if dt is None:
        return fmt_dt(value)
    local = dt.astimezone(REPORT_TZ)
    return f"{local.strftime('%d.%m.%Y %H:%M')} {local.strftime('%Z')}"


def tz_label() -> str:
    """e.g. `Europe/Zurich (CEST)` — resolved for *now*, so a report
    generated in winter says CET."""
    now = datetime.now(REPORT_TZ)
    return f"{REPORT_TZ.key} ({now.strftime('%Z')})"


@dataclass
class SectionData:
    """What a section returns from its `build(...)`. The generator
    renders each one through Jinja2 with the section's template +
    context, then concatenates the resulting HTML fragments."""
    title: str                       # already-translated title for this section
    template: str                    # Jinja2 template name, relative to templates/
    context: dict[str, Any] = field(default_factory=dict)
    # Optional: section can opt out at build time (e.g. "alerts" with
    # zero alerts to render — return None instead of an empty section).
    skip: bool = False


@dataclass
class SectionMeta:
    name: str          # stable id, e.g. "graph_snapshot" — used in the API + URL
    order: int         # ascending; ties broken by registration order
    default: bool      # whether this section is included when caller doesn't list any
    builder: Callable[..., Awaitable[Optional[SectionData]]]


_REGISTRY: dict[str, SectionMeta] = {}


def register_section(*, name: str, order: int, default: bool = True):
    """Decorator: register a section builder. The builder must be
    `async` and accept (case, db, lang, agent_data) — additional
    kwargs may be added later (passed via **kwargs)."""
    def _wrap(fn: Callable[..., Awaitable[Optional[SectionData]]]) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"section '{name}' already registered")
        _REGISTRY[name] = SectionMeta(name=name, order=order, default=default, builder=fn)
        return fn
    return _wrap


def list_sections() -> list[SectionMeta]:
    """All registered sections, sorted by `order`."""
    return sorted(_REGISTRY.values(), key=lambda s: (s.order, s.name))


def get_section(name: str) -> Optional[SectionMeta]:
    return _REGISTRY.get(name)


# Tiny i18n helper used by every section. Keeping translations local
# to each section file keeps the modular promise — but the helper
# itself lives here so no section has to roll its own.

class SectionStrings:
    """Per-language string lookup with English fallback. Each section
    instantiates one of these at module-top with its own dict."""

    def __init__(self, strings: dict[str, dict[str, str]]):
        self._strings = strings
        if "en" not in strings:
            raise ValueError("section strings must include an 'en' fallback")

    def t(self, lang: str, key: str, **fmt: Any) -> str:
        bundle = self._strings.get(lang) or self._strings["en"]
        raw = bundle.get(key) or self._strings["en"].get(key) or key
        try:
            return raw.format(**fmt) if fmt else raw
        except Exception:
            return raw
