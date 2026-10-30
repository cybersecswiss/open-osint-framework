"""
Shared helpers for the Telegram OSINT tools.

Two collection paths live side by side:

* **keyless** (default) — scrapes the no-auth public web preview at
  ``https://t.me/s/<channel>``. Works out of the box, no credentials,
  but only sees what a channel exposes publicly (recent posts, no full
  history, no media bytes).
* **Telethon** (optional) — a real MTProto client. Unlocks full
  history, views/forwards/reply metadata, channel discovery,
  in-channel server-side search, auto-translation and media download.
  Activated only when ``TELEGRAM_API_ID`` + ``TELEGRAM_API_HASH`` +
  ``TELEGRAM_SESSION`` (a Telethon StringSession) are all resolvable —
  from the operator key store (Global-Admin → Settings) first, the
  container env second. See docs/operations.en.md "Telegram deep collection".

This module holds the config gate + query parsing + the keyless HTML
scraping so both ``telegram_runner`` (keyless) and
``telegram_telethon`` (authenticated) can reuse it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from schemas import credential

USER_AGENT = "OOF/1.0"
PREVIEW_URL = "https://t.me/s/{channel}"
# A public channel handle: 5-32 chars, starts with a letter, then
# letters/digits/underscores. Matches Telegram's own username rules.
CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Keyless preview: how many messages one page yields and how many pages
# we walk back before giving up (bounded so a huge channel can't hang
# the module). Telethon path uses TELEGRAM_DEFAULT_LIMIT instead.
PREVIEW_PAGE_MAX = 20
PREVIEW_MAX_PAGES = 5


# --- Config gate -----------------------------------------------------

@dataclass
class TelegramConfig:
    api_id: int | None
    api_hash: str | None
    session: str | None
    translate: bool
    translate_target: str
    download_media: bool
    media_dir: str
    max_media_mb: int
    default_limit: int
    # username-hunt across known crime channels
    crime_channels_file: str = "/app/config/crime_channels.txt"
    crime_channels_inline: str = ""
    # Handles handed over by the framework per run (`options.channels`), i.e.
    # the list the operator maintains in the Owner console. Same shape as
    # module-news's `options.feeds`: when it is non-empty it WINS, when it is
    # empty the module falls back to its own bundled file, so a fresh install
    # still sweeps something sensible on day one.
    crime_channels_supplied: list = field(default_factory=list)
    hunt_max_channels: int = 40
    hunt_concurrency: int = 8
    hunt_per_channel_limit: int = 60
    extra: dict = field(default_factory=dict)

    @property
    def telethon_enabled(self) -> bool:
        """True only when a full MTProto session is configured. Every
        Telegram tool degrades to the keyless path when this is False,
        exactly like the key-gated threat-intel modules degrade to a
        clear 'missing key' note."""
        return bool(self.api_id and self.api_hash and self.session)


def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def load_config(options: "dict | None" = None) -> TelegramConfig:
    """Build the config for one run.

    The three CREDENTIALS resolve through ``credential()``, i.e. the
    operator key store (Global-Admin → Settings, passed in the /run request
    as ``options.credentials``) wins and the container env is the fallback —
    the same rule every other key-gated runner follows. Reading them from
    ``os.environ`` only would mean a key saved in the panel never reaches
    the Telethon path: the panel would report the key as set, the Test
    button would validate the STORED value, and every Telegram tool would
    still run keyless with a "not configured" note.

    Everything else stays env-only on purpose. Those are operator tuning
    knobs (limits, concurrency, media handling), not secrets, and they
    belong to the deployment rather than to a search request — accepting
    them per request would let a caller raise its own limits.
    """
    raw_id = credential(options, "TELEGRAM_API_ID")
    try:
        api_id = int(raw_id) if raw_id else None
    except ValueError:
        api_id = None
    return TelegramConfig(
        api_id=api_id,
        api_hash=credential(options, "TELEGRAM_API_HASH") or None,
        session=credential(options, "TELEGRAM_SESSION") or None,
        translate=_as_bool(os.environ.get("TELEGRAM_TRANSLATE"), False),
        translate_target=(os.environ.get("TELEGRAM_TRANSLATE_TARGET") or "en").strip(),
        download_media=_as_bool(os.environ.get("TELEGRAM_DOWNLOAD_MEDIA"), False),
        media_dir=(os.environ.get("TELEGRAM_MEDIA_DIR") or "/data/telegram").strip(),
        max_media_mb=int(os.environ.get("TELEGRAM_MAX_MEDIA_MB") or "50"),
        default_limit=int(os.environ.get("TELEGRAM_DEFAULT_LIMIT") or "200"),
        crime_channels_file=(os.environ.get("TELEGRAM_CRIME_CHANNELS_FILE")
                             or "/app/config/crime_channels.txt").strip(),
        crime_channels_inline=(os.environ.get("TELEGRAM_CRIME_CHANNELS") or "").strip(),
        crime_channels_supplied=[
            str(c) for c in ((options or {}).get("channels") or []) if str(c).strip()
        ],
        hunt_max_channels=int(os.environ.get("TELEGRAM_HUNT_MAX_CHANNELS") or "40"),
        hunt_concurrency=int(os.environ.get("TELEGRAM_HUNT_CONCURRENCY") or "8"),
        hunt_per_channel_limit=int(os.environ.get("TELEGRAM_HUNT_PER_CHANNEL_LIMIT") or "60"),
    )


def load_crime_channels(cfg: TelegramConfig) -> list[str]:
    """Curated list of known crime/cybercrime channels to sweep for a
    username. Read fresh on every run (so operators can edit without a
    restart). Sources, in priority order, deduped + capped:

      1. ``options.channels`` — the list the operator maintains in the Owner
         console, handed over per run. When present it is used ALONE: the
         console is then the single place that decides what gets swept, and
         silently mixing in a stale file would make the panel's channel count
         a lie.
      2. ``TELEGRAM_CRIME_CHANNELS`` env (comma/space separated) — quick
         override without touching the file.
      3. ``crime_channels_file`` (one handle per line, ``#`` comments) —
         the bundled list, bind-mounted so it survives rebuilds.
    """
    raw: list[str] = []
    if cfg.crime_channels_supplied:
        raw = list(cfg.crime_channels_supplied)
    else:
        if cfg.crime_channels_inline:
            raw += re.split(r"[,\s]+", cfg.crime_channels_inline)
        try:
            with open(cfg.crime_channels_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.split("#", 1)[0].strip()
                    if line:
                        raw += re.split(r"[,\s]+", line)
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            pass

    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        h = normalize_handle(item)
        if h and h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return out[: cfg.hunt_max_channels]


def sanitize_username(query: str) -> str | None:
    """A username/alias to hunt for. Looser than a channel handle — any
    non-trivial token works. Returns None if too short to be meaningful
    (a 1-2 char search would match half of every channel)."""
    if not query:
        return None
    u = query.strip().lstrip("@").split()[0] if query.strip() else ""
    u = u.strip()
    return u if len(u) >= 3 else None


# --- Query parsing ---------------------------------------------------

def normalize_handle(handle: str) -> str | None:
    """Reduce a variety of user inputs (@name, t.me/name, full URL) to a
    bare public channel handle, or None if it isn't a valid one."""
    if not handle:
        return None
    h = handle.strip().lstrip("@")
    if h.startswith("https://t.me/"):
        h = h.split("https://t.me/", 1)[1].split("/", 1)[0]
    if h.startswith("t.me/"):
        h = h.split("t.me/", 1)[1].split("/", 1)[0]
    h = h.split("?", 1)[0].split("#", 1)[0]
    # Lower-case the handle: Telegram usernames are case-insensitive, and
    # the graph dedups telegram_channel nodes by (entity_type, label). This
    # keeps messenger's `@handle` labels/edge-keys identical to the
    # authenticated telegram module's canonical_channel_label(), so the same
    # channel collapses to ONE node instead of e.g. @Durov vs @durov.
    return h.lower() if CHANNEL_RE.match(h) else None


def parse_inline_options(query: str) -> tuple[str, dict]:
    """Pull ``key=value`` tokens (limit=, days=) out of the query so a
    parameter can ride along the single ``query`` field the orchestrator
    passes (it hard-codes ``options={}``). Returns the cleaned query +
    an options dict. Unknown keys are ignored and left in the query."""
    opts: dict = {}
    tokens = query.split()
    keep: list[str] = []
    for tok in tokens:
        m = re.fullmatch(r"(limit|days|max_media_mb)=(\d+)", tok)
        if m:
            opts[m.group(1)] = int(m.group(2))
        else:
            keep.append(tok)
    return " ".join(keep).strip(), opts


def split_channel_keyword(query: str) -> tuple[str | None, str]:
    """For in-channel keyword search the single query field carries both
    a channel and a search term. Accept ``@channel :: keyword`` or, as a
    fallback, ``@channel keyword`` (first token = channel)."""
    q = query.strip()
    if "::" in q:
        left, _, right = q.partition("::")
        return normalize_handle(left.strip()), right.strip()
    parts = q.split(None, 1)
    if not parts:
        return None, ""
    return normalize_handle(parts[0]), (parts[1].strip() if len(parts) > 1 else "")


# --- Keyless preview scraping ----------------------------------------

def _parse_message_block(msg) -> dict:
    text_el = msg.select_one(".tgme_widget_message_text")
    date_el = msg.select_one(".tgme_widget_message_date time")
    views_el = msg.select_one(".tgme_widget_message_views")
    return {
        "text": text_el.get_text(" ", strip=True)[:1000] if text_el else "",
        "date": date_el.get("datetime") if date_el else "",
        "views": views_el.get_text(strip=True) if views_el else "",
        "permalink": (msg.get("data-post") and f"https://t.me/{msg['data-post']}") or "",
    }


async def fetch_preview(handle: str, limit: int) -> tuple[dict, list[str]]:
    """Scrape the public web preview, walking older pages until ``limit``
    messages are collected or the channel runs out. Returns a dict with
    channel meta + messages, and a list of soft errors.

    Raises no exceptions for the caller — network problems come back as
    an error string so the tool never 500s."""
    headers = {"User-Agent": USER_AGENT}
    messages: list[dict] = []
    meta: dict = {"handle": handle}
    errors: list[str] = []
    before: str | None = None
    pages = 0
    max_pages = max(1, min(PREVIEW_MAX_PAGES, (limit + PREVIEW_PAGE_MAX - 1) // PREVIEW_PAGE_MAX))

    try:
        async with httpx.AsyncClient(timeout=20, headers=headers,
                                     follow_redirects=True) as client:
            while pages < max_pages and len(messages) < limit:
                url = PREVIEW_URL.format(channel=handle)
                params = {"before": before} if before else None
                r = await client.get(url, params=params)
                if r.status_code == 404:
                    return {}, [f"Telegram channel @{handle} not found"]
                if r.status_code != 200:
                    return {}, [f"Telegram HTTP {r.status_code}"]
                soup = BeautifulSoup(r.text, "html.parser")

                if pages == 0:
                    # Only a live public channel renders `.tgme_channel_info`.
                    # Private/banned/non-existent render `.tgme_page` without
                    # it (sometimes with a history-unavailable marker).
                    if soup.select_one(".tgme_channel_history_unavailable") or \
                       not soup.select_one(".tgme_channel_info"):
                        return {}, [f"Telegram channel @{handle} is private/unavailable"]
                    title_el = soup.select_one(".tgme_channel_info_header_title, .tgme_page_title")
                    descr_el = soup.select_one(".tgme_channel_info_description, .tgme_page_description")
                    counters = {}
                    for c in soup.select(".tgme_channel_info_counter"):
                        lab = c.select_one(".counter_type")
                        val = c.select_one(".counter_value")
                        if lab and val:
                            counters[lab.get_text(strip=True)] = val.get_text(strip=True)
                    meta.update({
                        "title": title_el.get_text(strip=True) if title_el else handle,
                        "description": descr_el.get_text(" ", strip=True) if descr_el else "",
                        "subscribers": counters.get("subscribers", ""),
                        "photos": counters.get("photos", ""),
                        "videos": counters.get("videos", ""),
                        "links": counters.get("links", ""),
                    })

                blocks = soup.select(".tgme_widget_message")
                if not blocks:
                    break
                for block in blocks:
                    messages.append(_parse_message_block(block))
                # `before` cursor = numeric id of the oldest message on
                # this page, so the next request returns still-older ones.
                first_post = blocks[0].get("data-post", "")
                oldest_id = first_post.split("/")[-1] if "/" in first_post else ""
                if not oldest_id or oldest_id == before:
                    break
                before = oldest_id
                pages += 1
    except httpx.TimeoutException:
        return meta, ["Telegram timeout (20s)"]
    except Exception as e:  # noqa: BLE001
        return meta, [f"Telegram error: {e}"]

    # Newest-first, capped to the requested limit.
    meta["messages"] = messages[:limit]
    return meta, errors
