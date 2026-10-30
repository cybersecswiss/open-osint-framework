import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.blockchain_runner import run_btc_lookup
from tools.blockscout_runner import run_blockscout
from tools.etherscan_runner import run_eth_lookup
from tools.goplus_runner import run_address_risk
from tools.misttrack_runner import run_misttrack

app = FastAPI(title="OSINT Module: Crypto Tracing", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="crypto",
    label_key="search.module_crypto",
    category="crypto",
    description_key="search.module_crypto_desc",
    tools=[
        ToolDescriptor(
            tool="blockchain_btc",
            reliability="A",
            label_key="search.tool_btc",
            query_types=["btc_address"],
            default_query_type="btc_address",
        ),
        ToolDescriptor(
            tool="etherscan_eth",
            reliability="A",
            label_key="search.tool_eth",
            query_types=["eth_address"],
            default_query_type="eth_address",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="blockscout",
            reliability="A",
            label_key="search.tool_blockscout",
            query_types=["eth_address"],
            default_query_type="eth_address",
        ),
        ToolDescriptor(
            # Keyless EVM address risk — the free floor under
            # wallet_attribution, whose provider dropped its free tier.
            # Reliability B: membership in a curated malicious-address
            # dataset (SlowMist, BlockSec, OFAC, Chainabuse), so an
            # observation by third parties rather than by us, and not a
            # reputation opinion either.
            tool="address_risk",
            reliability="B",
            latency_class="fast",
            label_key="search.tool_address_risk",
            query_types=["eth_address"],
            default_query_type="eth_address",
            description_key="search.tool_address_risk_desc",
        ),
        ToolDescriptor(
            tool="wallet_attribution",
            reliability="C",
            label_key="search.tool_wallet_attribution",
            query_types=["btc_address", "eth_address"],
            default_query_type="btc_address",
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
        if req.tool == "blockchain_btc":
            findings, edges, errors = await run_btc_lookup(req.query)
        elif req.tool == "etherscan_eth":
            findings, edges, errors = await run_eth_lookup(req.query, req.options)
        elif req.tool == "blockscout":
            findings, edges, errors = await run_blockscout(req.query, req.query_type)
        elif req.tool == "address_risk":
            findings, edges, errors = await run_address_risk(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "wallet_attribution":
            findings, edges, errors = await run_misttrack(req.query, req.query_type, req.options)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
