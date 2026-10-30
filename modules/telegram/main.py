"""
OSINT Module: Telegram (MTProto / Telethon deep collection).

Framework-conformant module wrapping the standalone Telethon scanner.
Serves the three canonical endpoints (/health, /manifest, /run) and a
single shared Telethon session held by the TelegramScanner.

Unlike the keyless `messenger` module, this one performs authenticated
MTProto collection (full channel scans, user/phone/geo lookups). It
needs a pre-authorized Telethon session file (see docs/operations.en.md). If the
session is missing or unauthorized the module still starts but every
tool returns a clean error — mirroring the "missing key" degradation of
the key-gated modules, so it never takes the whole stack down.
"""
import asyncio
import hashlib
import logging
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI

from schemas import (
    ManifestResponse,
    RunRequest,
    RunResponse,
    ToolDescriptor,
    credential,
    make_run_response,
)
from scanner import TelegramScanner
from dispatch import dispatch, SUPPORTED_TOOLS
from forensics import collection_meta, append_audit

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("osint.module.telegram")

app = FastAPI(title="OSINT Module: Telegram", docs_url=None, redoc_url=None)

scanner: TelegramScanner | None = None
account_id = None
ready = False
init_error: str | None = None

# Guards the late (re-)authentication attempt in _ensure_scanner, plus a
# memo of credential pairs that already failed so a missing session file
# doesn't mean a fresh Telethon connect on every single run request.
_init_lock = asyncio.Lock()
_failed_creds: set[str] = set()


MANIFEST = ManifestResponse(
    name="telegram",
    label_key="search.module_telegram",
    category="messenger",
    description_key="search.module_telegram_desc",
    tools=[
        ToolDescriptor(
            tool="telegram_scan",
            reliability="B",
            label_key="search.tool_telegram_scan",
            description_key="search.tool_telegram_scan_desc",
            query_types=["tg_channel"],
            default_query_type="tg_channel",
        ),
        ToolDescriptor(
            tool="telegram_channel_info",
            reliability="B",
            label_key="search.tool_telegram_channel_info",
            description_key="search.tool_telegram_channel_info_desc",
            query_types=["tg_channel"],
            default_query_type="tg_channel",
        ),
        ToolDescriptor(
            # Renamed — see the note in modules/messenger.
            # The label key already said `telegram_deep_search`; only the
            # tool name lagged behind.
            tool="telegram_deep_search",
            reliability="C",
            label_key="search.tool_telegram_deep_search",
            description_key="search.tool_telegram_deep_search_desc",
            query_types=["tg_search"],
            default_query_type="tg_search",
        ),
        ToolDescriptor(
            tool="telegram_user_lookup",
            reliability="B",
            label_key="search.tool_telegram_user_lookup",
            description_key="search.tool_telegram_user_lookup_desc",
            # `username` too: a generic alias search resolves the same
            # value as a Telegram @handle, so the deep module joins
            # username fan-outs (needs an authenticated session; degrades
            # to a clean error otherwise).
            query_types=["tg_user", "username"],
            default_query_type="tg_user",
        ),
        ToolDescriptor(
            tool="telegram_phone_lookup",
            reliability="B",
            label_key="search.tool_telegram_phone_lookup",
            description_key="search.tool_telegram_phone_lookup_desc",
            query_types=["phone"],
            default_query_type="phone",
        ),
        ToolDescriptor(
            tool="telegram_geo",
            reliability="C",
            label_key="search.tool_telegram_geo",
            description_key="search.tool_telegram_geo_desc",
            query_types=["tg_geo"],
            default_query_type="tg_geo",
        ),
    ],
)


async def _connect(api_id_raw: str | None, api_hash: str | None, source: str) -> None:
    """Open the shared Telethon session. Sets the module globals and never
    raises — a failure degrades every tool to a clean error instead of
    taking the container down."""
    global scanner, account_id, ready, init_error
    if not api_id_raw or not api_hash:
        init_error = "TELEGRAM_API_ID / TELEGRAM_API_HASH not set (keyless mode)"
        return
    try:
        scanner = TelegramScanner(
            api_id=int(api_id_raw),
            api_hash=api_hash,
            session_name=os.getenv("TELEGRAM_SESSION_NAME", "osint_scanner"),
        )
        await scanner.connect()
        try:
            me = await scanner.client.get_me()
            account_id = me.id if me else None
        except Exception:
            account_id = None
        ready = True
        init_error = None
        logger.info("Telegram module ready (account_id=%s, credentials from %s)",
                    account_id, source)
    except Exception as e:  # noqa: BLE001 — degrade cleanly, never crash the container
        init_error = f"{type(e).__name__}: {e}"
        ready = False
        scanner = None
        logger.warning("Telegram module could not authenticate (%s): %s",
                       source, init_error)


async def _ensure_scanner(options: dict | None) -> None:
    """Second chance at authentication using the credentials the framework
    sends with the run request.

    The startup hook only sees the container env, so an API id/hash saved in
    the Global-Admin key store — which is where operators are told to put
    them — never reached this module: every tool reported "not
    authenticated" while the panel showed the key as set. Retried here under
    a lock, and a credential pair that fails (typically a missing or revoked
    session file, which the panel cannot supply) is remembered so the next
    request doesn't pay for the same doomed connect again.
    """
    if ready:
        return
    api_id = credential(options, "TELEGRAM_API_ID")
    api_hash = credential(options, "TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        return
    fingerprint = hashlib.sha256(f"{api_id}:{api_hash}".encode()).hexdigest()
    if fingerprint in _failed_creds:
        return
    async with _init_lock:
        if ready or fingerprint in _failed_creds:  # another request won the race
            return
        await _connect(api_id, api_hash, "run request")
        if not ready:
            _failed_creds.add(fingerprint)


@app.on_event("startup")
async def _startup() -> None:
    await _connect(os.getenv("TELEGRAM_API_ID"), os.getenv("TELEGRAM_API_HASH"),
                   "environment")
    if not ready:
        logger.warning("Telegram module inactive: %s — will retry with the "
                       "operator key store on the first run request", init_error)


@app.on_event("shutdown")
async def _shutdown() -> None:
    if scanner is not None:
        try:
            await scanner.disconnect()
        except Exception:
            pass


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "module": MANIFEST.name,
        "telegram_authenticated": ready,
        "account_id": account_id,
        "tools": SUPPORTED_TOOLS,
    }


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    start = time.time()
    findings, edges, errors = [], [], []

    # Credentials may only exist in the operator key store, which the
    # startup hook cannot see — try once more with what this request carries.
    await _ensure_scanner(req.options)

    if not ready or scanner is None:
        errors.append(
            "telegram module not authenticated: "
            + (init_error or "no Telethon session")
            + " — configure TELEGRAM_API_ID/HASH and a pre-authorized session "
            "(see docs/operations.en.md)"
        )
    else:
        options = dict(req.options or {})
        if req.tool in ("", "telegram_scan") and "limit_messages" not in options:
            options["limit_messages"] = int(os.getenv("MESSAGE_LIMIT", "100"))
        try:
            findings, edges, errors = await dispatch(req.tool, scanner, req.query, options)
        except Exception as e:  # noqa: BLE001 — never surface a 500
            errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    response = make_run_response(req.job_id, req.tool, start, findings, edges, errors)

    # Evidentiary trail: the framework RunResponse has no `collection`
    # field, so we fold the collection metadata into the hash-chained
    # audit log instead (enabled via AUDIT_LOG_PATH). Contract stays clean.
    log_record = response.model_dump()
    log_record["collection"] = collection_meta(req.tool, req.query, account_id)
    append_audit(log_record)

    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8090")),
    )
