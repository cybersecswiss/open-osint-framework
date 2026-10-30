"""
Optional Telethon-backed deep collection.

Only reached when :func:`telegram_common.TelegramConfig.telethon_enabled`
is True. Every import of a heavy/optional dependency (telethon,
deep_translator, langdetect) is done lazily inside the functions so the
module still boots and the keyless path still works even if these aren't
installed or the session is missing.

Nothing here performs interactive auth: the operator produces a
StringSession once, out of band (see docs/operations.en.md), and drops it into
``TELEGRAM_SESSION``. At runtime we only ``connect()`` and assert the
session is already authorized — never ``start()`` with a phone/code.
"""
from __future__ import annotations

import hashlib
import logging
import os
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from schemas import EdgeResult, Finding
from tools.telegram_common import EMAIL_RE, TelegramConfig

log = logging.getLogger("module-messenger.telegram.telethon")

# Cache translator instances per source→target language pair.
_translators: dict[str, object] = {}


class TelethonUnavailable(RuntimeError):
    """Raised when the authenticated path can't run (lib missing, session
    invalid). The runner catches it and falls back to keyless."""


@asynccontextmanager
async def _client(cfg: TelegramConfig):
    try:
        from telethon import TelegramClient  # noqa: PLC0415
        from telethon.sessions import StringSession  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - depends on image build
        raise TelethonUnavailable(f"telethon not installed: {e}") from e

    client = TelegramClient(StringSession(cfg.session), cfg.api_id, cfg.api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise TelethonUnavailable(
                "TELEGRAM_SESSION is not authorized — regenerate the "
                "StringSession (see docs/operations.en.md)."
            )
        yield client
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


# --- translation -----------------------------------------------------

def _translate(text: str, target: str) -> tuple[str, str]:
    """Best-effort translate to `target`. Returns (translated, src_lang).
    Never raises — translation is a nice-to-have, not load-bearing."""
    if not text.strip():
        return "", ""
    try:
        from langdetect import detect  # noqa: PLC0415
        src = detect(text)
    except Exception:  # noqa: BLE001
        src = ""
    if src == target or not src:
        # still attempt if detection failed; skip if clearly same lang
        if src == target:
            return text, src
    try:
        from deep_translator import GoogleTranslator  # noqa: PLC0415
        key = f"{src or 'auto'}->{target}"
        tr = _translators.get(key)
        if tr is None:
            tr = GoogleTranslator(source=(src or "auto"), target=target)
            _translators[key] = tr
        # GoogleTranslator caps at ~5000 chars per call; chunk long text.
        chunks = [text[i:i + 4500] for i in range(0, len(text), 4500)]
        out = " ".join(tr.translate(c) for c in chunks if c.strip())
        return out or text, src
    except Exception as e:  # noqa: BLE001
        log.debug("translate failed: %s", e)
        return text, src


# --- media -----------------------------------------------------------

async def _download_media(client, msg, cfg: TelegramConfig, job_dir: str) -> dict | None:
    """Download a message's media if within the size cap. Returns
    metadata (never the bytes) for the entity graph, or None."""
    if not getattr(msg, "media", None):
        return None
    try:
        size = getattr(getattr(msg, "file", None), "size", None) or 0
        if size and size > cfg.max_media_mb * 1024 * 1024:
            return {"skipped": "too_large", "size": size}
        os.makedirs(job_dir, exist_ok=True)
        path = await client.download_media(msg, file=job_dir)
        if not path or not os.path.isfile(path):
            return None
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                h.update(block)
        return {
            "filename": os.path.basename(path),
            "size": os.path.getsize(path),
            "mime": getattr(getattr(msg, "file", None), "mime_type", "") or "",
            "sha256": h.hexdigest(),
        }
    except Exception as e:  # noqa: BLE001
        log.debug("media download failed: %s", e)
        return None


def _zip_job_dir(job_dir: str, cfg: TelegramConfig, job_id: str) -> str | None:
    """Zip a job's downloaded media into MEDIA_DIR/<job_id>.zip so the
    backend download-proxy can stream it. Returns the zip path or None."""
    if not os.path.isdir(job_dir) or not os.listdir(job_dir):
        return None
    zip_path = os.path.join(cfg.media_dir, f"{job_id}.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(job_dir):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, arcname=os.path.relpath(full, job_dir))
        return zip_path
    except Exception as e:  # noqa: BLE001
        log.debug("zip failed: %s", e)
        return None


# --- public entrypoints ----------------------------------------------

async def collect_channel(
    cfg: TelegramConfig, handle: str, *, limit: int, days: int | None,
    job_id: str,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    """Deep-collect a channel: full message metadata, optional
    translation + media download."""
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    since = None
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
    job_dir = os.path.join(cfg.media_dir, job_id)
    media_downloaded = 0

    async with _client(cfg) as client:
        entity = await client.get_entity(handle)
        title = getattr(entity, "title", handle)
        subs = None
        try:
            from telethon.tl.functions.channels import GetFullChannelRequest  # noqa: PLC0415
            full = await client(GetFullChannelRequest(entity))
            subs = getattr(full.full_chat, "participants_count", None)
        except Exception:  # noqa: BLE001
            pass

        chan_data = {"handle": handle, "title": title, "subscribers": subs,
                     "source": "telethon"}
        messages_meta: list[dict] = []
        async for msg in client.iter_messages(entity, limit=limit):
            if since and msg.date and msg.date < since:
                break
            text = msg.message or ""
            item = {
                "id": msg.id,
                "date": msg.date.isoformat() if msg.date else "",
                "text": text[:2000],
                "views": getattr(msg, "views", None),
                "forwards": getattr(msg, "forwards", None),
                "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
                "permalink": f"https://t.me/{handle}/{msg.id}",
            }
            if cfg.translate and text:
                item["text_translated"], item["src_lang"] = _translate(text, cfg.translate_target)
            if cfg.download_media:
                media = await _download_media(client, msg, cfg, job_dir)
                if media:
                    item["media"] = media
                    if "filename" in media:
                        media_downloaded += 1
            # emails mentioned in a post → edges
            for m in EMAIL_RE.finditer(text):
                edges.append(EdgeResult(
                    from_entity=f"telegram_channel:@{handle}",
                    to_entity=f"email:{m.group(0).lower()}",
                    relation="mentions", confidence=0.6))
            messages_meta.append(item)

        chan_data["messages"] = messages_meta
        chan_data["message_count"] = len(messages_meta)

        if cfg.download_media and media_downloaded:
            zip_path = _zip_job_dir(job_dir, cfg, job_id)
            if zip_path:
                chan_data["media_zip"] = True
                chan_data["media_zip_job"] = job_id
                chan_data["media_count"] = media_downloaded

        findings.append(Finding(
            entity_type="telegram_channel", platform="telegram",
            label=f"@{handle}", url=f"https://t.me/{handle}",
            confidence=0.95, data=chan_data))

    return findings, edges, errors


async def discover_channels(
    cfg: TelegramConfig, keyword: str, *, limit: int,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    """Global channel discovery by keyword via SearchGlobalRequest /
    contacts.Search."""
    findings: list[Finding] = []
    async with _client(cfg) as client:
        from telethon.tl.functions.contacts import SearchRequest  # noqa: PLC0415
        res = await client(SearchRequest(q=keyword, limit=min(limit, 50)))
        for chat in getattr(res, "chats", []) or []:
            uname = getattr(chat, "username", None)
            if not uname:
                continue
            findings.append(Finding(
                entity_type="telegram_channel", platform="telegram",
                label=f"@{uname}", url=f"https://t.me/{uname}",
                confidence=0.7,
                data={"handle": uname, "title": getattr(chat, "title", ""),
                      "matched_keyword": keyword, "source": "telethon_search"}))
    return findings, [], []


async def hunt_username(
    cfg: TelegramConfig, username: str, channels: list[str], *, per_channel_limit: int,
) -> tuple[list[dict], list[str]]:
    """Sweep a list of channels for messages mentioning ``username``,
    reusing a single client connection. Returns a list of per-channel hit
    dicts (only channels with ≥1 hit) plus soft errors. Server-side
    search over full history — far better than the keyless preview."""
    results: list[dict] = []
    errors: list[str] = []
    async with _client(cfg) as client:
        for handle in channels:
            try:
                entity = await client.get_entity(handle)
                hits: list[dict] = []
                async for msg in client.iter_messages(
                    entity, search=username, limit=per_channel_limit
                ):
                    text = msg.message or ""
                    hit = {
                        "id": msg.id,
                        "date": msg.date.isoformat() if msg.date else "",
                        "text": text[:1000],
                        "views": getattr(msg, "views", None),
                        "permalink": f"https://t.me/{handle}/{msg.id}",
                    }
                    if cfg.translate and text:
                        hit["text_translated"], hit["src_lang"] = _translate(
                            text, cfg.translate_target)
                    hits.append(hit)
                if hits:
                    results.append({"channel": handle, "hits": hits})
            except Exception as e:  # noqa: BLE001 — skip a bad channel, keep going
                errors.append(f"{handle}: {type(e).__name__}")
    return results, errors


async def search_messages(
    cfg: TelegramConfig, handle: str, keyword: str, *, limit: int,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    """Server-side in-channel keyword search over full history."""
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    async with _client(cfg) as client:
        entity = await client.get_entity(handle)
        hits: list[dict] = []
        async for msg in client.iter_messages(entity, search=keyword, limit=limit):
            text = msg.message or ""
            hit = {
                "id": msg.id,
                "date": msg.date.isoformat() if msg.date else "",
                "text": text[:2000],
                "views": getattr(msg, "views", None),
                "permalink": f"https://t.me/{handle}/{msg.id}",
            }
            if cfg.translate and text:
                hit["text_translated"], hit["src_lang"] = _translate(text, cfg.translate_target)
            hits.append(hit)
        findings.append(Finding(
            entity_type="telegram_message", platform="telegram",
            label=f"@{handle} ~ {keyword}",
            url=f"https://t.me/{handle}", confidence=0.85,
            data={"handle": handle, "keyword": keyword, "hit_count": len(hits),
                  "messages": hits, "source": "telethon_search"}))
        edges.append(EdgeResult(
            from_entity=f"telegram_message:@{handle} ~ {keyword}",
            to_entity=f"telegram_channel:@{handle}",
            relation="found_in", confidence=0.85))
    return findings, edges, []
