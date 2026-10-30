import logging
from extractors.ioc import extract_iocs
from schemas import Finding, EdgeResult, SearchOptions

logger = logging.getLogger(__name__)


def _clean(target: str) -> str:
    if "t.me/" in target:
        target = target.split("t.me/")[-1].rstrip("/").split("#")[0]
    return target


async def _search_channel(client, channel: str, keyword: str, options: SearchOptions):
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    entity = await client.get_entity(_clean(channel))
    channel_username = getattr(entity, "username", None) or str(entity.id)
    channel_label = f"t.me/{channel_username}"

    async for message in client.iter_messages(entity, search=keyword, limit=options.limit):
        if not message.text and not message.media:
            continue
        msg_label = f"msg_{entity.id}_{message.id}"
        findings.append(Finding(
            entity_type="telegram_message",
            label=msg_label,
            data={
                "id": message.id,
                "text": message.text or "",
                "date": str(message.date),
                "views": message.views or 0,
                "forwards": message.forwards or 0,
                "author_id": str(message.sender_id) if message.sender_id else "unknown",
                "channel_id": entity.id,
                "channel": channel_username,
                "matched_keyword": keyword,
            },
        ))
        edges.append(EdgeResult(
            from_entity=f"telegram_message:{msg_label}",
            to_entity=f"telegram_channel:{channel_label}",
            relation="IN_CHANNEL",
        ))

        if options.extract_iocs:
            for ioc in extract_iocs(message.text):
                findings.append(Finding(
                    entity_type="telegram_ioc",
                    label=ioc["value"],
                    data={"ioc_type": ioc["type"], "source_message": msg_label},
                ))
                edges.append(EdgeResult(
                    from_entity=f"telegram_message:{msg_label}",
                    to_entity=f"telegram_ioc:{ioc['value']}",
                    relation="MENTIONS",
                ))

    return findings, edges


async def run(client, query: str, options_dict: dict):
    options = SearchOptions(**(options_dict or {}))
    keyword = query.strip()
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    if not keyword:
        return findings, edges, ["no search keyword provided"]
    if not options.channels:
        return findings, edges, ["no channels specified in options.channels"]

    for channel in options.channels:
        channel = channel.strip()
        if not channel:
            continue
        try:
            f, e = await _search_channel(client, channel, keyword, options)
            findings.extend(f)
            edges.extend(e)
        except Exception as ex:
            errors.append(f"{channel}: {ex}")

    return findings, edges, errors
