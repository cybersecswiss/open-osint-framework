import logging
from telethon.tl.functions.channels import GetFullChannelRequest, GetChannelRecommendationsRequest
from schemas import Finding, EdgeResult, ChannelInfoOptions
from labels import canonical_channel_label

logger = logging.getLogger(__name__)


def _clean(target: str) -> str:
    if "t.me/" in target:
        target = target.split("t.me/")[-1].rstrip("/").split("#")[0]
    return target


def _channel_finding(entity, extra: dict | None = None) -> Finding:
    username = getattr(entity, "username", None) or str(entity.id)
    data = {
        "id": entity.id,
        "username": username,
        "title": getattr(entity, "title", "") or "",
        "member_count": getattr(entity, "participants_count", None),
        "is_verified": getattr(entity, "verified", False),
        "is_scam": getattr(entity, "scam", False),
    }
    if extra:
        data.update(extra)
    return Finding(
        entity_type="telegram_channel",
        label=canonical_channel_label(entity),
        url=f"https://t.me/{username}" if getattr(entity, "username", None) else None,
        data=data,
    )


async def _info(client, target: str, options: ChannelInfoOptions):
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    entity = await client.get_entity(_clean(target))
    full = await client(GetFullChannelRequest(entity))
    fc = full.full_chat

    extra = {
        "description": getattr(fc, "about", "") or "",
        "online_count": getattr(fc, "online_count", None),
        "linked_chat_id": getattr(fc, "linked_chat_id", None),
        "slowmode_seconds": getattr(fc, "slowmode_seconds", None),
        "can_view_participants": getattr(fc, "can_view_participants", None),
        "hidden_prehistory": getattr(fc, "hidden_prehistory", None),
        "participants_count": getattr(fc, "participants_count", None),
    }
    channel_finding = _channel_finding(entity, extra)
    findings.append(channel_finding)
    channel_label = channel_finding.label

    linked_id = getattr(fc, "linked_chat_id", None)
    if linked_id:
        edges.append(EdgeResult(
            from_entity=f"telegram_channel:{channel_label}",
            to_entity=f"telegram_channel:chat_{linked_id}",
            relation="LINKED_DISCUSSION",
        ))

    if options.recommendations:
        try:
            rec = await client(GetChannelRecommendationsRequest(channel=entity))
            for chat in getattr(rec, "chats", [])[: options.recommendations_limit]:
                rec_username = getattr(chat, "username", None) or str(chat.id)
                rec_label = canonical_channel_label(chat)
                findings.append(Finding(
                    entity_type="telegram_channel",
                    label=rec_label,
                    url=f"https://t.me/{rec_username}" if getattr(chat, "username", None) else None,
                    data={
                        "id": chat.id,
                        "username": rec_username,
                        "title": getattr(chat, "title", "") or "",
                        "member_count": getattr(chat, "participants_count", None),
                        "source": "recommendation",
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=f"telegram_channel:{channel_label}",
                    to_entity=f"telegram_channel:{rec_label}",
                    relation="SIMILAR_TO",
                ))
        except Exception as e:
            logger.warning("Channel recommendations failed for %s: %s", target, e)

    return findings, edges


async def run(client, query: str, options_dict: dict):
    options = ChannelInfoOptions(**(options_dict or {}))
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    targets = [t.strip() for t in query.split(",") if t.strip()]
    for target in targets:
        try:
            f, e = await _info(client, target, options)
            findings.extend(f)
            edges.extend(e)
        except Exception as ex:
            errors.append(f"{target}: {ex}")
    return findings, edges, errors
