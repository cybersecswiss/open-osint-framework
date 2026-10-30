import os
import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.ahmia_runner import run_ahmia
from tools.paste_runner import run_paste_search
from tools.seizure_runner import run_seizure_watch
from tools.onion_scrape_runner import run_onion_scrape

app = FastAPI(title="OSINT Module: Darknet & Paste", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="darknet",
    label_key="search.module_darknet",
    category="darknet",
    description_key="search.module_darknet_desc",
    tools=[
        ToolDescriptor(
            tool="ahmia",
            reliability="D",
            label_key="search.tool_ahmia",
            query_types=["keyword", "username", "email", "btc_address"],
            default_query_type="keyword",
        ),
        ToolDescriptor(
            tool="paste_search",
            reliability="D",
            label_key="search.tool_paste",
            query_types=["keyword", "username", "email", "domain"],
            default_query_type="keyword",
        ),
        ToolDescriptor(
            tool="seizure_watch",
            reliability="C",
            label_key="search.tool_seizure_watch",
            query_types=["domain"],
            default_query_type="domain",
        ),
    ],
)

# onion_scrape is OFF by default: it fetches the CONTENT of hidden services
# over Tor (text only; services on Ahmia's abuse blacklist are always
# refused, and nothing is fetched when the list cannot be loaded). Enable it
# deliberately with ENABLE_ONION_SCRAPE=true in .env.
ONION_SCRAPE_ENABLED = os.getenv("ENABLE_ONION_SCRAPE", "false").strip().lower() in ("1", "true", "yes")
if ONION_SCRAPE_ENABLED:
    MANIFEST.tools.append(ToolDescriptor(
        # The pivot step after a darknet search: reads a service for contact
        # addresses, wallets, messenger IDs and links to other services.
        tool="onion_scrape",
        reliability="D",
        label_key="search.tool_onion_scrape",
        description_key="search.tool_onion_scrape_desc",
        query_types=["onion_address"],
        default_query_type="onion_address",
    ))


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "ahmia":
            findings, edges, errors = await run_ahmia(req.query)
        elif req.tool == "paste_search":
            findings, edges, errors = await run_paste_search(req.query)
        elif req.tool == "onion_scrape":
            if not ONION_SCRAPE_ENABLED:
                errors.append("onion_scrape is disabled (ENABLE_ONION_SCRAPE=false).")
            else:
                findings, edges, errors = await run_onion_scrape(req.query)
        elif req.tool == "seizure_watch":
            findings, edges, errors = await run_seizure_watch(req.query, req.query_type, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
