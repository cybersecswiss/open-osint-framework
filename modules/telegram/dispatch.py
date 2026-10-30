from schemas import ScanOptions
from operations import user, phone, channel, search, geo

OPERATION_HANDLERS = {
    "telegram_user_lookup": user.run,
    "telegram_phone_lookup": phone.run,
    "telegram_channel_info": channel.run,
    "telegram_deep_search": search.run,
    "telegram_geo": geo.run,
}

SUPPORTED_TOOLS = ["telegram_scan"] + list(OPERATION_HANDLERS.keys())


def _parse_search_query(query: str, options: dict) -> tuple[str, dict]:
    """
    telegram_search needs a channel list, but the orchestrator forwards
    an empty options dict. Support an inline syntax so the tool is usable
    from the single query string the framework provides:

        "@chan1,@chan2 :: keyword"   (channels left of '::', keyword right)

    If options.channels is already set (direct API caller), it wins.
    """
    opts = dict(options or {})
    if not opts.get("channels") and "::" in query:
        chan_part, _, kw = query.partition("::")
        opts["channels"] = [
            c.strip() for c in chan_part.replace(" ", ",").split(",") if c.strip()
        ]
        query = kw.strip()
    return query, opts


async def dispatch(tool: str, scanner, query: str, options: dict):
    if not tool or tool == "telegram_scan":
        channels = [c.strip() for c in query.split(",") if c.strip()]
        opts = ScanOptions(**(options or {}))
        return await scanner.scan_channels(channels, opts)

    handler = OPERATION_HANDLERS.get(tool)
    if handler is None:
        return [], [], [f"unknown tool: {tool} (supported: {', '.join(SUPPORTED_TOOLS)})"]

    if tool == "telegram_deep_search":
        query, options = _parse_search_query(query, options)

    return await handler(scanner.client, query, options or {})
