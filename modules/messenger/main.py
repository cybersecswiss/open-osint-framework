import time

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.discord_runner import run_discord_invite
from tools.discord_snowflake_runner import run_discord_snowflake
from tools.discord_deep_runner import run_discord_deep
from tools.phone_messenger_runner import run_phone_messenger
from tools.lyzem_runner import run_telegram_global_search
from tools.tgstat_runner import run_tgstat
from tools.telegram_common import load_config
from tools.telegram_runner import (
    run_telegram_channel,
    run_telegram_message_search,
    run_telegram_search,
    run_telegram_username_hunt,
)

app = FastAPI(title="OSINT Module: Messenger Intel", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="messenger",
    label_key="search.module_messenger",
    category="messenger",
    description_key="search.module_messenger_desc",
    tools=[
        ToolDescriptor(
            tool="telegram_channel",
            reliability="C",
            label_key="search.tool_telegram",
            query_types=["tg_channel"],
            default_query_type="tg_channel",
        ),
        ToolDescriptor(
            # Keyless channel analytics (subscriber count etc.) via TGStat.
            tool="tgstat",
            reliability="C",
            label_key="search.tool_tgstat",
            query_types=["tg_channel"],
            default_query_type="tg_channel",
        ),
        ToolDescriptor(
            tool="telegram_username_hunt",
            reliability="C",
            label_key="search.tool_telegram_username_hunt",
            query_types=["username"],
            default_query_type="username",
        ),
        ToolDescriptor(
            # Renamed. It used to be `telegram_search`, which
            # module-telegram ALSO declared — and a shared tool name is not
            # cosmetic: the orchestrator keys the Admiralty reliability by
            # tool name, so every finding of this D-rated tool was being
            # rated with the other module's C, or the other way round
            # depending on load order. The name now says what it does:
            # it builds deep links, it does not search Telegram.
            tool="telegram_deeplink_search",
            reliability="D",
            label_key="search.tool_telegram_deeplink_search",
            query_types=["tg_search", "keyword"],
            default_query_type="tg_search",
        ),
        ToolDescriptor(
            # Real global Telegram discovery (Lyzem scrape) — returns
            # actual channels, not just deep-links like telegram_search.
            tool="telegram_global_search",
            reliability="D",
            label_key="search.tool_telegram_global",
            query_types=["tg_search", "keyword"],
            default_query_type="keyword",
        ),
        ToolDescriptor(
            tool="telegram_message_search",
            reliability="D",
            label_key="search.tool_telegram_msg_search",
            query_types=["tg_msg_search"],
            default_query_type="tg_msg_search",
        ),
        ToolDescriptor(
            tool="discord_invite",
            reliability="B",
            label_key="search.tool_discord",
            query_types=["discord_invite"],
            default_query_type="discord_invite",
        ),
        ToolDescriptor(
            # Keyless: Discord ID → exact creation timestamp (snowflake).
            tool="discord_snowflake",
            reliability="A",
            label_key="search.tool_discord_snowflake",
            query_types=["discord_id"],
            default_query_type="discord_id",
        ),
        ToolDescriptor(
            # Key-gated (DISCORD_BOT_TOKEN): ID → full public profile.
            tool="discord_deep",
            reliability="C",
            label_key="search.tool_discord_deep",
            query_types=["discord_id"],
            default_query_type="discord_id",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="phone_messenger",
            reliability="D",
            label_key="search.tool_phone_messenger",
            query_types=["phone"],
            default_query_type="phone",
        ),
    ],
)


@app.get("/health")
async def health():
    # A health probe carries no request options, so it can only see the
    # container env — a credential that lives solely in the operator key
    # store is invisible here. Say which source this reflects instead of
    # reporting "deep collection off": the run path resolves the store
    # first and may well be authenticated when this says False.
    cfg = load_config()
    return {"status": "ok", "module": MANIFEST.name,
            "telegram_deep_collection": cfg.telethon_enabled,
            "telegram_deep_collection_source":
                "env only — the operator key store is resolved per run request"}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.get("/artifact/{job_id}")
async def artifact(job_id: str):
    """Serve a downloaded-media ZIP for a Telethon collection job. Only
    ever populated when the authenticated path ran with media download
    enabled; keyless searches never produce one. The backend proxies
    this to the analyst as a download button. Job id is sanitised to a
    plain filename to avoid path traversal."""
    import os
    import re
    cfg = load_config()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", job_id)
    path = os.path.join(cfg.media_dir, f"{safe}.zip")
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"error": "no artifact for job"})
    return FileResponse(path, media_type="application/zip",
                        filename=f"telegram-{safe}.zip")


class TelegramValidate(BaseModel):
    api_id: str = ""
    api_hash: str = ""
    session: str = ""


@app.post("/validate-telegram")
async def validate_telegram(body: TelegramValidate):
    """Verify Telegram credentials + a StringSession by actually opening
    it with Telethon. Called by the backend's Global-Admin Settings
    'Test' button. Returns {valid, message, account?}."""
    if not body.api_id or not body.api_hash:
        return {"valid": False, "message": "API ID and API Hash are required."}
    if not body.session:
        return {"valid": False, "message": "No StringSession provided."}
    try:
        api_id = int(str(body.api_id).strip())
    except ValueError:
        return {"valid": False, "message": "API ID must be numeric."}
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(body.session.strip()), api_id, body.api_hash.strip())
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {"valid": False, "message": "Session not authorized (expired or revoked)."}
            me = await client.get_me()
            account = (f"@{me.username}" if getattr(me, "username", None)
                       else (str(me.id) if me else "?"))
            return {"valid": True, "message": "Session authorized.", "account": account}
        finally:
            await client.disconnect()
    except Exception as e:  # noqa: BLE001
        return {"valid": False, "message": f"Telethon error: {type(e).__name__}: {e}"}


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "telegram_channel":
            findings, edges, errors = await run_telegram_channel(req.query, req.options, req.job_id)
        elif req.tool == "telegram_username_hunt":
            findings, edges, errors = await run_telegram_username_hunt(req.query, req.options, req.job_id)
        elif req.tool == "telegram_deeplink_search":
            findings, edges, errors = await run_telegram_search(req.query, req.options, req.job_id)
        elif req.tool == "telegram_global_search":
            findings, edges, errors = await run_telegram_global_search(req.query, req.options, req.job_id)
        elif req.tool == "tgstat":
            findings, edges, errors = await run_tgstat(req.query, req.options, req.job_id)
        elif req.tool == "telegram_message_search":
            findings, edges, errors = await run_telegram_message_search(req.query, req.options, req.job_id)
        elif req.tool == "discord_invite":
            findings, edges, errors = await run_discord_invite(req.query)
        elif req.tool == "discord_snowflake":
            findings, edges, errors = await run_discord_snowflake(req.query, req.options, req.job_id)
        elif req.tool == "discord_deep":
            findings, edges, errors = await run_discord_deep(req.query, req.options, req.job_id)
        elif req.tool == "phone_messenger":
            findings, edges, errors = await run_phone_messenger(req.query, req.query_type, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
