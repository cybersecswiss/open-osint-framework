import time

from fastapi import FastAPI
from pydantic import BaseModel

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.news_search_runner import feed_health, harvest, run_news_search

app = FastAPI(title="OSINT Module: News & RSS", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="news",
    label_key="search.module_news",
    category="news",
    description_key="search.module_news_desc",
    tools=[
        ToolDescriptor(
            tool="news_search",
            latency_class="fast",
            reliability="C",
            label_key="search.tool_news_search",
            description_key="search.tool_news_search_desc",
            query_types=["keyword"],
            default_query_type="keyword",
        ),
    ],
)


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name}


@app.get("/feed-health")
async def health_per_feed():
    """Per-feed fetch health, for the operator console.

    In-memory: it reflects this process since its last restart. The backend
    merges it with a persisted copy so "failing since" survives a restart.
    """
    return {"health": feed_health()}


class HarvestRequest(BaseModel):
    feeds: list[dict] = []


@app.post("/harvest")
async def harvest_feeds(req: HarvestRequest):
    """Fetch the given feeds whole and return their parsed entries.

    Called by the backend's scheduled harvester (not by analysts). No
    keyword filtering here — the backend persists everything and searches
    the DB. See tools.news_search_runner.harvest.
    """
    return await harvest(req.feeds)


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "news_search":
            findings, edges, errors = await run_news_search(req.query, req.options)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
