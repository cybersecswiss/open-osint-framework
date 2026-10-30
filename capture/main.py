"""Evidence capture — a web page as it was, with a hash, at a stated time.

A finding in a case is a link. When the profile, post or listing is deleted,
all that is left is the claim that it was there. This service fetches the page
once, in a real browser, and returns

  * a full-page **screenshot** (PNG) — what a person saw,
  * an **MHTML archive** — the page with its images and styles in one file,
    openable in any Chromium browser,
  * the **SHA-256** of each, the final URL after redirects, the HTTP status,
    the time, the user agent and whether Tor was used.

It stores nothing. The framework hands the result to the tenant's own data
store; the operator keeps only the hashes.

## Why every request goes through Python

The browser fetches arbitrary, investigator-supplied URLs from inside the
operator's network. Two layers keep that from becoming a way into it:

1. **Network.** This container sits on its own Docker network with only the
   api and Tor. Postgres, the license server, Keycloak and the updater are not
   reachable from here at all.
2. **Per request.** Every request the page makes — the document, every image,
   every script, and **every redirect hop** — is checked against
   `safe_fetch.assert_public_url` before it goes out. Redirects are followed
   in `_follow()`, never by the browser: Chromium follows a 3xx inside its
   network stack without calling the route handler again (measured, see
   `_follow`), so handing it a redirect would skip the check.

Honest limit (as in safe_fetch): DNS rebinding between the check and the
connect is not closed. WebSockets are not routed; the page gets no time to
open one that matters before the capture ends.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright, Error as PWError, Route
from pydantic import BaseModel, Field

from safe_fetch import BlockedURL, assert_public_url, is_onion

log = logging.getLogger("capture")
logging.basicConfig(level=logging.INFO)

TOR_PROXY = os.environ.get("TOR_SOCKS_PROXY", "socks5://tor:9050").replace("socks5h://", "socks5://")
NAV_TIMEOUT_MS = int(os.environ.get("CAPTURE_NAV_TIMEOUT_MS", "40000"))
ONION_NAV_TIMEOUT_MS = int(os.environ.get("CAPTURE_ONION_NAV_TIMEOUT_MS", "70000"))
MAX_SCREENSHOT_HEIGHT = int(os.environ.get("CAPTURE_MAX_HEIGHT", "16000"))
MAX_ARCHIVE_BYTES = int(os.environ.get("CAPTURE_MAX_ARCHIVE_BYTES", str(25 * 1024 * 1024)))
MAX_PARALLEL = int(os.environ.get("CAPTURE_MAX_PARALLEL", "2"))
UA = os.environ.get(
    "CAPTURE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

_sem = asyncio.Semaphore(MAX_PARALLEL)
app = FastAPI(title="capture")


class CaptureIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@app.get("/health")
async def health():
    return {"status": "ok"}


MAX_HOPS = 5
_REDIRECTS = (301, 302, 303, 307, 308)


async def _check(url: str, onion_mode: bool) -> None:
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise BlockedURL(f"unsupported scheme: {scheme or '(none)'}")
    host = urlparse(url).hostname or ""
    if onion_mode and is_onion(host):
        return                               # Tor path: no local resolution
    await assert_public_url(url)


async def _follow(fetch, url: str, onion_mode: bool, chain: list[str]):
    """Fetch with redirects followed HERE, every hop checked.

    Measured: after `route.fulfill()` with a 3xx, Chromium follows
    the redirect inside its network stack and never calls the route handler
    again — a public page could bounce the browser to 169.254.169.254 with
    no check at all. So a redirect is never handed to the browser.
    """
    for _ in range(MAX_HOPS + 1):
        await _check(url, onion_mode)
        resp = await fetch(url)
        loc = resp.headers.get("location")
        if resp.status not in _REDIRECTS or not loc:
            return resp, url
        url = urljoin(url, loc)
        chain.append(url)
    raise BlockedURL(f"too many redirects (>{MAX_HOPS})")


async def _guard(route: Route, onion_mode: bool, blocked: list[str]) -> None:
    req = route.request
    if urlparse(req.url).scheme in ("data", "blob"):
        await route.continue_()
        return
    try:
        resp, _ = await _follow(
            lambda u: route.fetch(url=u, max_redirects=0, timeout=NAV_TIMEOUT_MS),
            req.url, onion_mode, [])
        await route.fulfill(response=resp)
    except BlockedURL as e:
        blocked.append(f"{req.url[:200]} ({e})")
        await route.abort("blockedbyclient")
    except PWError as e:
        # A subresource that fails is part of what the page looked like; the
        # capture goes on. The main document failing surfaces in goto().
        log.info("request failed %s: %s", req.url[:120], str(e)[:120])
        try:
            await route.abort("failed")
        except PWError:
            pass


@app.post("/capture")
async def capture(payload: CaptureIn):
    url = payload.url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="only http(s) URLs can be captured")
    onion_mode = is_onion(parsed.hostname)
    if not onion_mode:
        try:
            await assert_public_url(url)
        except BlockedURL as e:
            raise HTTPException(status_code=422, detail=f"blocked: {e}")

    blocked: list[str] = []
    async with _sem, async_playwright() as pw:
        launch = {"args": ["--disable-dev-shm-usage"]}
        if onion_mode:
            launch["proxy"] = {"server": TOR_PROXY}
        browser = await pw.chromium.launch(**launch)
        try:
            context = await browser.new_context(
                # Set on the context too: route.fetch() below issues the
                # requests, and it must take the same (Tor) path as the page.
                proxy={"server": TOR_PROXY} if onion_mode else None,
                user_agent=UA, viewport={"width": 1366, "height": 900},
                # A page with a broken certificate is still evidence of what
                # was served; the fact is recorded, not hidden.
                ignore_https_errors=True, service_workers="block",
                accept_downloads=False, locale="de-CH")
            await context.route("**/*", lambda r: _guard(r, onion_mode, blocked))
            page = await context.new_page()
            started = datetime.now(timezone.utc)
            # Resolve the main document's redirects first (same context, so
            # same proxy, UA and cookies), every hop checked, and load the
            # final URL — so relative links resolve against the real page and
            # the chain is on record.
            chain: list[str] = []
            try:
                _, target = await _follow(
                    lambda u: page.request.fetch(u, max_redirects=0, timeout=NAV_TIMEOUT_MS),
                    url, onion_mode, chain)
            except BlockedURL as e:
                raise HTTPException(status_code=422, detail=f"blocked: {e}")
            except PWError as e:
                raise HTTPException(status_code=502, detail=f"page could not be loaded: {str(e)[:300]}")
            try:
                resp = await page.goto(target, wait_until="load",
                                       timeout=ONION_NAV_TIMEOUT_MS if onion_mode else NAV_TIMEOUT_MS)
            except PWError as e:
                raise HTTPException(status_code=502, detail=f"page could not be loaded: {str(e)[:300]}")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PWError:
                pass                         # a page that never idles is still capturable
            captured_at = datetime.now(timezone.utc)

            height = await page.evaluate("() => document.documentElement.scrollHeight") or 0
            truncated = height > MAX_SCREENSHOT_HEIGHT
            shot = await page.screenshot(
                type="png", full_page=True,
                clip={"x": 0, "y": 0, "width": 1366, "height": MAX_SCREENSHOT_HEIGHT} if truncated else None)

            archive_type = "multipart/related"
            try:
                cdp = await context.new_cdp_session(page)
                snap = await cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                archive = (snap.get("data") or "").encode("utf-8")
            except PWError:
                archive = b""
            if not archive or len(archive) > MAX_ARCHIVE_BYTES:
                # Too large (or unavailable) as a self-contained archive: keep
                # the rendered HTML instead and say so.
                archive = (await page.content()).encode("utf-8")[:MAX_ARCHIVE_BYTES]
                archive_type = "text/html"

            headers = {}
            if resp is not None:
                all_h = await resp.all_headers()
                headers = {k: v for k, v in all_h.items()
                           if k in ("server", "content-type", "date", "last-modified",
                                    "x-powered-by", "via", "cf-ray")}
            return {
                "url": url,
                "final_url": page.url,
                "http_status": resp.status if resp is not None else None,
                "title": (await page.title())[:500],
                "requested_at": started.isoformat(),
                "captured_at": captured_at.isoformat(),
                "via_tor": onion_mode,
                "user_agent": UA,
                "response_headers": headers,
                "blocked_requests": blocked[:50],
                "redirect_chain": chain,
                "screenshot_png_b64": base64.b64encode(shot).decode(),
                "screenshot_sha256": _sha(shot),
                "screenshot_truncated": truncated,
                "page_height": height,
                "archive_b64": base64.b64encode(archive).decode(),
                "archive_sha256": _sha(archive),
                "archive_type": archive_type,
                "archive_bytes": len(archive),
            }
        finally:
            await browser.close()
