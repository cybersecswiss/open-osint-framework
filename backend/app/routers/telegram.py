"""
Telegram media-artifact download proxy.

The messenger module's optional Telethon path can download a channel's
media and bundle it into a per-job ZIP that lives in a module-side
volume. This route lets an authenticated analyst pull that ZIP through
the framework API (the module isn't exposed to the browser directly).

Keyless searches never produce an artifact, so in the default
configuration this route simply returns 404 — it exists so the frontend
"Download media" button works the moment the deep path is enabled.
"""
from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import get_current_user
from app.config import settings

log = logging.getLogger("osint.telegram")
router = APIRouter(tags=["telegram"])

_JOB_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@router.get("/telegram/artifact/{job_id}")
async def download_artifact(job_id: str, user: dict = Depends(get_current_user)):
    if not _JOB_RE.match(job_id):
        raise HTTPException(status_code=400, detail="invalid job id")

    url = f"{settings.module_messenger_url}/artifact/{job_id}"
    client = httpx.AsyncClient(timeout=60)
    try:
        req = client.build_request("GET", url)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("artifact proxy to %s failed: %s", url, e)
        raise HTTPException(status_code=502, detail="messenger module unreachable")

    if resp.status_code == 404:
        await resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=404, detail="no media artifact for this job")
    if resp.status_code != 200:
        await resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"module returned {resp.status_code}")

    async def _stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _stream(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="telegram-{job_id}.zip"'},
    )
