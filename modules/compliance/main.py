import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.opensanctions_runner import run_opensanctions

app = FastAPI(title="OSINT Module: Compliance & Sanctions", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="compliance",
    label_key="search.module_compliance",
    category="compliance",
    description_key="search.module_compliance_desc",
    tools=[
        ToolDescriptor(
            tool="opensanctions",
            reliability="B",
            label_key="search.tool_opensanctions",
            # Name/company (keyword) + crypto wallets (OFAC crypto SDN).
            query_types=["keyword", "btc_address", "eth_address"],
            default_query_type="keyword",
            requires_key=True,
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
        if req.tool == "opensanctions":
            findings, edges, errors = await run_opensanctions(req.query, req.query_type, req.options)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
