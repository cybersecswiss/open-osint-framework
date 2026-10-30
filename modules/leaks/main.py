import base64
import json
import os
import time

from fastapi import FastAPI
from pydantic import BaseModel

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.hibp_runner import run_hibp
from tools.holehe_runner import run_holehe
from tools.intelx_runner import run_intelx_link
from tools.ghunt_runner import run_ghunt
from tools.hudsonrock_runner import run_hudsonrock

app = FastAPI(title="OSINT Module: Leaks & Breaches", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="leaks",
    label_key="search.module_leaks",
    category="leaks",
    description_key="search.module_leaks_desc",
    tools=[
        ToolDescriptor(
            tool="holehe",
            reliability="C",
            label_key="search.tool_holehe",
            query_types=["email"],
            default_query_type="email",
        ),
        ToolDescriptor(
            tool="hibp",
            reliability="B",
            label_key="search.tool_hibp",
            query_types=["email"],
            default_query_type="email",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="intelx",
            reliability="C",
            label_key="search.tool_intelx",
            query_types=["email", "domain", "username"],
            default_query_type="email",
        ),
        ToolDescriptor(
            tool="ghunt",
            reliability="C",
            label_key="search.tool_ghunt",
            query_types=["email", "gaia"],
            default_query_type="email",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="hudsonrock",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_hudsonrock",
            # Keyless (free osint-tools API); an optional HUDSONROCK_API_KEY
            # only raises limits, so requires_key stays False.
            query_types=["email", "username", "domain"],
            default_query_type="email",
        ),
    ],
)


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


def _master_from_cred(raw: str) -> str:
    """Accept a raw Android master token (aas_et/…) or a base64 creds.m and
    return the master token."""
    raw = (raw or "").strip()
    if raw.startswith("aas_et/"):
        return raw
    try:
        data = json.loads(base64.b64decode(raw).decode())
        return (data.get("android") or {}).get("master_token", "") or ""
    except Exception:  # noqa: BLE001
        return ""


class GhuntValidate(BaseModel):
    creds: str = ""


class GhuntDerive(BaseModel):
    companion: str = ""  # base64 from the GHunt Companion extension, or an oauth_token


def _write_creds(master_or_b64: str) -> str:
    """Write a creds.m under a fresh temp HOME and return the HOME path.
    Accepts a master token (wrapped) or a full base64 creds.m."""
    import tempfile
    raw = (master_or_b64 or "").strip()
    home = tempfile.mkdtemp(prefix="ghunt_home_")
    cdir = os.path.join(home, ".malfrats", "ghunt")
    os.makedirs(cdir, exist_ok=True)
    if raw.startswith("aas_et/"):
        creds_b64 = base64.b64encode(json.dumps({
            "cookies": {"a": "a"}, "osids": {"a": "a"},
            "android": {"master_token": raw, "authorization_tokens": {}},
        }).encode()).decode()
    else:
        creds_b64 = raw
    with open(os.path.join(cdir, "creds.m"), "w", encoding="utf-8") as f:
        f.write(creds_b64)
    return home


@app.post("/validate-ghunt")
async def validate_ghunt(body: GhuntValidate):
    """Test button: check the Android master token against Google. NOTE this
    is a token-level check; the actual email/gaia lookup additionally
    regenerates browser cookies from the token, which can fail separately —
    the search surfaces that real error."""
    master = _master_from_cred(body.creds)
    if not master:
        return {"valid": False, "message": "No master token / creds provided."}
    try:
        from ghunt.helpers import auth
        from ghunt.helpers.utils import get_httpx_client
        client = get_httpx_client()
        try:
            ok = await auth.check_master_token(client, master)
        finally:
            await client.aclose()
        if ok:
            return {"valid": True, "message": "Master token valid. (If a search "
                                              "still fails, it's the cookie step — "
                                              "run the search to see the real error.)"}
        return {"valid": False, "message": "Master token invalid or revoked — re-generate."}
    except Exception as e:  # noqa: BLE001
        return {"valid": False, "message": f"GHunt error: {type(e).__name__}: {e}"}


@app.post("/ghunt/derive")
async def ghunt_derive(body: GhuntDerive):
    """In-panel setup: turn the GHunt Companion extension's base64 blob (or a
    raw oauth_token) into a long-lived master token — the server side of
    `ghunt login`, so no CLI is needed. The browser step (getting the blob
    from a logged-in burner account) is still done by the operator."""
    val = (body.companion or "").strip()
    if not val:
        return {"ok": False, "message": "Paste the GHunt Companion base64 (or an oauth_token)."}
    oauth_token = ""
    if val.startswith("oauth2_4/"):
        oauth_token = val
    else:
        try:
            data = json.loads(base64.b64decode(val).decode())
            oauth_token = data.get("oauth_token", "") or ""
        except Exception:  # noqa: BLE001
            oauth_token = val if val.startswith("oauth2_4/") else ""
    if not oauth_token:
        return {"ok": False, "message": "Could not read an oauth_token from that input."}
    try:
        from ghunt.helpers import auth
        from ghunt.helpers.utils import get_httpx_client
        client = get_httpx_client()
        try:
            master_token, _services, owner_email, owner_name = \
                await auth.android_master_auth(client, oauth_token)
        finally:
            await client.aclose()
        if not master_token:
            return {"ok": False, "message": "Google did not return a master token "
                                            "(the oauth_token may be expired)."}
        return {"ok": True, "master_token": master_token,
                "account": owner_email or owner_name or "?", "name": owner_name}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"GHunt derive failed: {type(e).__name__}: {e}"}


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "holehe" and req.query_type == "email":
            findings, edges, errors = await run_holehe(req.query, req.job_id)
        elif req.tool == "hibp" and req.query_type == "email":
            findings, edges, errors = await run_hibp(req.query, req.options)
        elif req.tool == "intelx":
            findings, edges, errors = await run_intelx_link(req.query, req.query_type)
        elif req.tool == "ghunt" and req.query_type in ("email", "gaia"):
            findings, edges, errors = await run_ghunt(
                req.query, req.options, req.job_id, req.query_type)
        elif req.tool == "hudsonrock" and req.query_type in ("email", "username", "domain"):
            findings, edges, errors = await run_hudsonrock(req.query, req.query_type, req.options)
        else:
            errors.append(f"Unknown tool/query_type combination: {req.tool}/{req.query_type}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
