import os
import time

from fastapi import FastAPI

from schemas import NOTE_PREFIX, ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.cupidcrawl_runner import run_cupidcrawl

app = FastAPI(title="OSINT Module: Dating & Adult", docs_url=None, redoc_url=None)

# OFF by default. Whether a username has profiles on dating or adult
# platforms is information about a person's sex life — a special category
# of personal data (Swiss FADP art. 5 lit. c, GDPR art. 9). The operator
# switches it on deliberately in .env (ENABLE_DATING_SEARCH=true); while it
# is off the module advertises no tool, so the search form never offers it.
ENABLED = os.getenv("ENABLE_DATING_SEARCH", "false").strip().lower() in ("1", "true", "yes")

WARNING = (NOTE_PREFIX + "Sensitive search: dating/adult profiles reveal information "
           "about a person's sex life (special category of personal data). Use only "
           "with a specific legal basis and purpose, and keep the results restricted.")

MANIFEST = ManifestResponse(
    name="dating",
    label_key="search.module_dating",
    category="people",
    description_key="search.module_dating_desc",
    tools=[
        ToolDescriptor(
            tool="cupidcrawl",
            reliability="C",
            label_key="search.tool_cupidcrawl",
            description_key="search.tool_cupidcrawl_desc",
            query_types=["username"],
            default_query_type="username",
        ),
    ] if ENABLED else [],
)


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name, "enabled": ENABLED}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "cupidcrawl":
            if not ENABLED:
                errors.append("cupidcrawl is disabled (ENABLE_DATING_SEARCH=false).")
            else:
                findings, edges, errors = await run_cupidcrawl(req.query, req.job_id)
                errors = [WARNING] + list(errors)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
