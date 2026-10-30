import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.handle_sweep_runner import run_handle_sweep
from tools.sherlock_runner import run_sherlock
from tools.whatsmyname_runner import run_whatsmyname
from tools.user_scanner_runner import run_user_scanner
from tools.linkook_runner import run_linkook

app = FastAPI(title="OSINT Module: Alias / Username Pivoting", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="alias",
    label_key="search.module_alias",
    category="alias",
    description_key="search.module_alias_desc",
    tools=[
        ToolDescriptor(
            tool="sherlock",
            latency_class="slow",
            reliability="C",
            label_key="search.tool_sherlock",
            query_types=["username"],
            default_query_type="username",
        ),
        ToolDescriptor(
            tool="whatsmyname",
            latency_class="slow",
            reliability="C",
            label_key="search.tool_whatsmyname",
            query_types=["username"],
            default_query_type="username",
        ),
        ToolDescriptor(
            tool="user_scanner",
            reliability="C",
            label_key="search.tool_user_scanner",
            query_types=["username", "email"],
            default_query_type="username",
        ),
        ToolDescriptor(
            tool="linkook",
            reliability="C",
            label_key="search.tool_linkook",
            query_types=["username"],
            default_query_type="username",
        ),
        ToolDescriptor(
            tool="handle_sweep",
            latency_class="slow",
            reliability="C",
            label_key="search.tool_handle_sweep",
            description_key="search.tool_handle_sweep_desc",
            query_types=["username"],
            default_query_type="username",
        ),
    ],
)


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
        if req.tool == "sherlock":
            findings, edges, errors = await run_sherlock(req.query, req.job_id)
        elif req.tool == "whatsmyname":
            findings, edges, errors = await run_whatsmyname(req.query, req.job_id)
        elif req.tool == "user_scanner":
            findings, edges, errors = await run_user_scanner(req.query, req.query_type, req.job_id)
        elif req.tool == "linkook":
            findings, edges, errors = await run_linkook(req.query, req.job_id)
        elif req.tool == "handle_sweep":
            findings, edges, errors = await run_handle_sweep(req.query, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
