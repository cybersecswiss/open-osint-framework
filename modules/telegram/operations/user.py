import logging
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.messages import GetCommonChatsRequest
from telethon.tl.types import (
    UserStatusOnline,
    UserStatusOffline,
    UserStatusRecently,
    UserStatusLastWeek,
    UserStatusLastMonth,
)
from extractors.media import hash_bytes
from schemas import Finding, EdgeResult, UserLookupOptions
from labels import canonical_channel_label

logger = logging.getLogger(__name__)


def _status_label(status) -> dict:
    if isinstance(status, UserStatusOnline):
        return {"presence": "online", "expires": str(getattr(status, "expires", ""))}
    if isinstance(status, UserStatusOffline):
        return {"presence": "offline", "last_seen": str(getattr(status, "was_online", ""))}
    if isinstance(status, UserStatusRecently):
        return {"presence": "recently"}
    if isinstance(status, UserStatusLastWeek):
        return {"presence": "last_week"}
    if isinstance(status, UserStatusLastMonth):
        return {"presence": "last_month"}
    return {"presence": "unknown"}


async def _hash_photos(client, entity, limit: int) -> list[dict]:
    out = []
    try:
        photos = await client.get_profile_photos(entity, limit=limit)
    except Exception as e:
        logger.warning("Could not fetch profile photos: %s", e)
        return out
    for photo in photos:
        try:
            data = await client.download_media(photo, file=bytes)
            if data:
                entry = hash_bytes(data)
                entry["photo_id"] = getattr(photo, "id", None)
                out.append(entry)
        except Exception as e:
            logger.warning("Could not hash profile photo: %s", e)
    return out


async def _lookup(client, target: str, options: UserLookupOptions):
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    entity = await client.get_entity(target)
    username = getattr(entity, "username", None) or str(entity.id)
    user_label = f"@{username}"

    full_data = {}
    try:
        full = await client(GetFullUserRequest(entity))
        fu = full.full_user
        full_data = {
            "bio": getattr(fu, "about", None),
            "common_chats_count": getattr(fu, "common_chats_count", None),
            "blocked": getattr(fu, "blocked", None),
            "phone_calls_available": getattr(fu, "phone_calls_available", None),
            "personal_channel_id": getattr(fu, "personal_channel_id", None),
        }
        birthday = getattr(fu, "birthday", None)
        if birthday is not None:
            full_data["birthday"] = {
                "day": getattr(birthday, "day", None),
                "month": getattr(birthday, "month", None),
                "year": getattr(birthday, "year", None),
            }
    except Exception as e:
        logger.warning("GetFullUser failed for %s: %s", target, e)

    try:
        photo_count = len(await client.get_profile_photos(entity, limit=options.photo_limit))
    except Exception:
        photo_count = None

    data = {
        "id": entity.id,
        "username": username,
        "first_name": getattr(entity, "first_name", "") or "",
        "last_name": getattr(entity, "last_name", "") or "",
        "phone": getattr(entity, "phone", None),
        "is_bot": getattr(entity, "bot", False),
        "is_scam": getattr(entity, "scam", False),
        "is_fake": getattr(entity, "fake", False),
        "is_verified": getattr(entity, "verified", False),
        "is_premium": getattr(entity, "premium", False),
        "is_restricted": getattr(entity, "restricted", False),
        "lang_code": getattr(entity, "lang_code", None),
        "profile_photos": photo_count,
        "status": _status_label(getattr(entity, "status", None)),
    }
    data.update({k: v for k, v in full_data.items() if v is not None})

    if options.hash_photos:
        hashed = await _hash_photos(client, entity, options.photo_limit)
        if hashed:
            data["photo_hashes"] = hashed

    findings.append(Finding(
        entity_type="telegram_user",
        label=user_label,
        url=f"https://t.me/{username}" if getattr(entity, "username", None) else None,
        data=data,
    ))

    if options.include_common_chats:
        try:
            common = await client(GetCommonChatsRequest(
                user_id=entity, max_id=0, limit=options.common_chats_limit
            ))
            for chat in common.chats:
                chat_username = getattr(chat, "username", None) or str(chat.id)
                chat_label = canonical_channel_label(chat)
                findings.append(Finding(
                    entity_type="telegram_channel",
                    label=chat_label,
                    url=f"https://t.me/{chat_username}" if getattr(chat, "username", None) else None,
                    data={
                        "id": chat.id,
                        "username": chat_username,
                        "title": getattr(chat, "title", "") or "",
                        "source": "common_chat",
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=f"telegram_user:{user_label}",
                    to_entity=f"telegram_channel:{chat_label}",
                    relation="COMMON_CHAT",
                ))
        except Exception as e:
            logger.warning("GetCommonChats failed for %s: %s", target, e)

    return findings, edges


async def run(client, query: str, options_dict: dict):
    options = UserLookupOptions(**(options_dict or {}))
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    targets = [t.strip() for t in query.split(",") if t.strip()]
    for target in targets:
        try:
            f, e = await _lookup(client, target, options)
            findings.extend(f)
            edges.extend(e)
        except Exception as ex:
            errors.append(f"{target}: {ex}")
    return findings, edges, errors
