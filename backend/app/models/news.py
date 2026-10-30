"""
Persistent news / RSS cache — framework (operator) DB.

Why store news at all when there is a live path (module-news `/run`)?
Because live-fetching every analyst search re-hits the same public feeds
and gets us rate-limited — the module's own comment records ReadErrors
from admin.ch caused exactly this. A background harvester polls the
feeds on a polite schedule (authority/police/cyber hourly, the rest
every 30 min) and writes rows here; the analyst search then reads the
DB, so a search is instant and never touches an authority server.

Sovereignty: news is public, operator-global data (the feed list lives
in the Owner console). It never belongs to a tenant, so it sits in the
framework DB, not the customer data-agent — no boundary crossed.

Timestamps are NAIVE UTC on purpose. The whole framework DB uses naive
columns; writing tz-aware datetimes here makes asyncpg raise DataError.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NewsArticle(Base):
    """One de-duplicated article harvested from an RSS/Atom feed.

    Dedup: `dedup_key` is UNIQUE and the harvester upserts with
    ON CONFLICT DO NOTHING, so re-polling an archive feed that still
    lists an old item is a no-op. `id` is a deterministic uuid5 of the
    same key, so the row's identity is stable across re-harvests.
    """
    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # Stable identity of the article across polls (normalized URL, or a
    # hash of source+title when a feed omits links). UNIQUE → the dedup.
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    # lower(title + " " + summary): the single column the trigram index
    # accelerates, so an analyst's substring-AND search stays exactly the
    # semantics of the old live search but runs off an index.
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    published: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # naive UTC
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    feed_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_kind: Mapped[str | None] = mapped_column(String(32), index=True)
    source_lang: Mapped[str | None] = mapped_column(String(8))


class NewsFeedPollState(Base):
    """Per-feed harvest bookkeeping, so the poller knows which feeds are
    due (last poll older than the feed's kind interval) and the console
    can show when a source last answered.

    Keyed by the feed URL (stable across restarts, unlike the module's
    in-memory health). The URL is stored with the `{{max}}` placeholder
    already substituted, i.e. exactly the URL that was fetched.
    """
    __tablename__ = "news_feed_poll_state"

    feed_url: Mapped[str] = mapped_column(String(500), primary_key=True)
    feed_id: Mapped[str | None] = mapped_column(String(64))
    source_kind: Mapped[str | None] = mapped_column(String(32))
    last_poll_attempt: Mapped[datetime | None] = mapped_column(DateTime)
    last_poll_ok: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_fails: Mapped[int] = mapped_column(Integer, default=0)
