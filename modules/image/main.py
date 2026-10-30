import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.code_runner import run_code_scan
from tools.image_runner import run_exif_gps, run_visual_geolocate

app = FastAPI(title="OSINT Module: Image", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="image",
    label_key="search.module_image",
    category="media",
    description_key="search.module_image_desc",
    tools=[
        ToolDescriptor(
            tool="exif_gps",
            reliability="B",
            label_key="search.tool_exif_gps",
            query_types=["image_url"],
            default_query_type="image_url",
        ),
        ToolDescriptor(
            # QR / DataMatrix / Aztec / barcodes. Reliability A: the decoder
            # either recovers the error-corrected payload or it fails — this
            # is a measurement of the image, not a third party's opinion, and
            # it is the only tool in the module that can say so.
            tool="code_scan",
            reliability="A",
            latency_class="fast",
            label_key="search.tool_code_scan",
            query_types=["image_url"],
            default_query_type="image_url",
            description_key="search.tool_code_scan_desc",
        ),
        ToolDescriptor(
            tool="visual_geolocate",
            reliability="E",
            label_key="search.tool_visual_geolocate",
            query_types=["image_url"],
            default_query_type="image_url",
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
        if req.tool == "exif_gps":
            findings, edges, errors = await run_exif_gps(req.query, req.query_type, req.job_id)
        elif req.tool == "code_scan":
            findings, edges, errors = await run_code_scan(
                req.query, req.query_type, req.job_id)
        elif req.tool == "visual_geolocate":
            findings, edges, errors = await run_visual_geolocate(
                req.query, req.query_type, req.options, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
