"""Image-OSINT — pull hard forensic facts out of an image an investigator
found (forum upload, seized device, direct host link).

Two tools, deliberately separate because their trust levels differ:

* ``exif_gps`` — KEYLESS, authoritative. Downloads the image and reads the
  embedded EXIF metadata: camera make/model, capture timestamp, editing
  software and, when present, the GPS coordinates the camera stamped in.
  A GPS hit is *hard evidence of where the shot was taken* — emitted as a
  ``location`` node with a keyless OSM reverse-geocoded place name.

* ``visual_geolocate`` — KEY-GATED (reuses the operator's Gemini key). When
  an image has NO GPS (the common case — most platforms strip EXIF), this
  asks a vision model to ESTIMATE the location from visible cues (signage,
  architecture, vegetation, licence plates). The result is clearly marked
  AI-ESTIMATED at low confidence — a lead to verify, never proof. No
  fabricated precision: if the model can't tell, it says so and we emit
  nothing.

Nothing here auto-chains: the investigator decides whether a geotag or an
AI guess belongs to their subject.
"""
from __future__ import annotations

import base64
import io
import logging
import os

import httpx

from safe_fetch import BlockedURL, assert_public_url

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

log = logging.getLogger("module-image")

MAX_BYTES = 25 * 1024 * 1024      # don't pull huge files into RAM
DOWNLOAD_TIMEOUT = 25.0
UA = "Mozilla/5.0 (compatible; OOF/1.0; +image-osint)"
GEMINI_MODEL = os.environ.get("AI_GEMINI_MODEL", "gemini-3.5-flash").strip()


# --------------------------------------------------------------------- helpers

async def _download(url: str) -> tuple[bytes | None, str, str | None]:
    """Fetch the image. Returns (bytes, content_type, error).

    The URL comes straight from the analyst, so it is validated before any
    socket opens. Without that check this is an SSRF: an ordinary
    user account could reach `license:9000`, `keycloak:8080` and
    `updater:9999` (the container with the Docker socket), and the returned
    error text distinguished a live service from a closed port from an
    unreachable network — an internal port scanner with a readable oracle.
    On a cloud host the same path reaches the metadata service.
    """
    if not url.lower().startswith(("http://", "https://")):
        return None, "", "provide a direct http(s) image URL."
    # One flat message for every refusal. Naming the reason (unresolvable vs
    # private vs blocked range) would hand back exactly the oracle this closes.
    BLOCKED = "blocked: the URL does not point at a public host."
    try:
        async with httpx.AsyncClient(
            timeout=DOWNLOAD_TIMEOUT, follow_redirects=False,
            headers={"User-Agent": UA},
        ) as client:
            # Redirects are followed by hand and re-validated per hop:
            # follow_redirects=True would let a public host bounce the fetch
            # to an internal address with nothing checking the new target.
            for _hop in range(4):
                try:
                    await assert_public_url(url)
                except BlockedURL:
                    return None, "", BLOCKED
                async with client.stream("GET", url) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            return None, "", f"download failed: HTTP {r.status_code}"
                        url = str(httpx.URL(url).join(loc))
                        continue
                    if r.status_code != 200:
                        return None, "", f"download failed: HTTP {r.status_code}"
                    ctype = r.headers.get("content-type", "").split(";")[0].strip()
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf += chunk
                        if len(buf) > MAX_BYTES:
                            return None, ctype, f"image exceeds {MAX_BYTES // (1024*1024)} MB cap."
                    return bytes(buf), ctype, None
            return None, "", BLOCKED
    except httpx.HTTPError as e:
        return None, "", f"download error: {type(e).__name__}: {e}"


def _img_label(url: str) -> str:
    """Stable, readable node label from the URL basename."""
    name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return name or url[:60]


def _dms_to_decimal(dms, ref) -> float | None:
    """EXIF GPS is (deg, min, sec) rationals + a N/S/E/W ref → signed decimal."""
    try:
        deg, minute, sec = (float(x) for x in dms)
        val = deg + minute / 60.0 + sec / 3600.0
        if str(ref).upper() in ("S", "W"):
            val = -val
        return round(val, 6)
    except Exception:  # noqa: BLE001
        return None


def _extract_exif(content: bytes) -> dict:
    """Parse EXIF into a flat dict. Missing/broken EXIF → {} (not an error)."""
    from PIL import ExifTags, Image

    out: dict = {}
    try:
        img = Image.open(io.BytesIO(content))
        out["format"] = img.format
        out["dimensions"] = f"{img.width}x{img.height}"
        exif = img.getexif()
    except Exception:  # noqa: BLE001 — not a parseable image
        return out
    if not exif:
        return out

    base = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    for src, dst in (("Make", "camera_make"), ("Model", "camera_model"),
                     ("Software", "software"), ("DateTime", "modified_at")):
        if base.get(src):
            out[dst] = str(base[src]).strip("\x00 ").strip()

    # Capture time + lens live in the Exif sub-IFD
    try:
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        subm = {ExifTags.TAGS.get(k, k): v for k, v in sub.items()}
        if subm.get("DateTimeOriginal"):
            out["taken_at"] = str(subm["DateTimeOriginal"]).strip("\x00 ").strip()
        if subm.get("LensModel"):
            out["lens"] = str(subm["LensModel"]).strip("\x00 ").strip()
    except Exception:  # noqa: BLE001
        pass

    # GPS sub-IFD
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if gps:
            g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}
            lat = _dms_to_decimal(g.get("GPSLatitude"), g.get("GPSLatitudeRef"))
            lon = _dms_to_decimal(g.get("GPSLongitude"), g.get("GPSLongitudeRef"))
            if lat is not None and lon is not None:
                out["gps"] = {"lat": lat, "lon": lon}
                if g.get("GPSAltitude") is not None:
                    try:
                        out["gps"]["altitude_m"] = round(float(g["GPSAltitude"]), 1)
                    except Exception:  # noqa: BLE001
                        pass
    except Exception:  # noqa: BLE001
        pass
    return out


async def _reverse_geocode(lat: float, lon: float) -> str | None:
    """Keyless OSM Nominatim reverse-geocode → human place name."""
    try:
        async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": UA}) as c:
            r = await c.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 16},
            )
            if r.status_code == 200:
                return r.json().get("display_name")
    except Exception:  # noqa: BLE001
        pass
    return None


# --------------------------------------------------------------------- exif_gps

async def run_exif_gps(
    query: str, query_type: str = "image_url", job_id: str = "adhoc"
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    url = (query or "").strip()
    content, ctype, err = await _download(url)
    if err:
        return [], [], [f"exif_gps: {err}"]
    if ctype and not (ctype.startswith("image/") or ctype == "application/octet-stream"):
        return [], [], [f"exif_gps: URL is not an image (content-type: {ctype})."]

    meta = _extract_exif(content)
    if not meta.get("format"):
        return [], [], ["exif_gps: could not decode the image."]

    label = _img_label(url)
    img_key = f"image:{label}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    gps = meta.pop("gps", None)
    findings.append(Finding(
        entity_type="image", platform="exif", label=label, url=url,
        confidence=0.9,
        data={**meta, "url": url, "source": "exif", "has_gps": bool(gps)},
    ))

    if gps:
        place = await _reverse_geocode(gps["lat"], gps["lon"])
        loc_label = place or f"{gps['lat']}, {gps['lon']}"
        findings.append(Finding(
            entity_type="location", platform="exif_gps", label=loc_label,
            url=f"https://www.openstreetmap.org/?mlat={gps['lat']}&mlon={gps['lon']}#map=16/{gps['lat']}/{gps['lon']}",
            confidence=0.9,
            data={"lat": gps["lat"], "lon": gps["lon"],
                  "altitude_m": gps.get("altitude_m"),
                  "place": place, "source": "exif_gps", "evidence": "camera GPS tag"},
        ))
        edges.append(EdgeResult(from_entity=img_key, to_entity=f"location:{loc_label}",
                                relation="geotagged_at", confidence=0.9))
    else:
        errors.append(f"{NOTE_PREFIX}No GPS tag embedded — try 'visual_geolocate' "
                      f"for an AI location estimate from the picture content.")

    # Camera as its own node so two photos from the same device link up.
    cam = " ".join(x for x in (meta.get("camera_make"), meta.get("camera_model")) if x)
    if cam:
        findings.append(Finding(
            entity_type="camera", platform="exif", label=cam, confidence=0.7,
            data={"make": meta.get("camera_make"), "model": meta.get("camera_model"),
                  "source": "exif"},
        ))
        edges.append(EdgeResult(from_entity=img_key, to_entity=f"camera:{cam}",
                                relation="taken_with", confidence=0.7))

    return findings, edges, errors


# ---------------------------------------------------------------- visual_geolocate

_GEO_PROMPT = (
    "You are a forensic image geolocation analyst. Study the image and estimate "
    "WHERE it was taken using only visible evidence: language on signs, "
    "architecture, road markings, licence-plate style, vegetation, terrain, sun "
    "position. Respond ONLY with JSON of this exact shape:\n"
    '{"identifiable": true|false, "place": "most specific place name you can '
    'justify or empty", "country": "country or empty", "lat": number|null, '
    '"lon": number|null, "confidence": 0.0-1.0, "reasoning": "the concrete '
    'visual cues you used"}\n'
    "Set identifiable=false and null coords if there is not enough evidence. "
    "NEVER invent precision — a whole-country guess is fine, a fake street is not."
)


async def run_visual_geolocate(
    query: str, query_type: str = "image_url", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "GEMINI_API_KEY")
    if not key:
        return [], [], ["visual_geolocate: needs the Gemini API key (Global-Admin "
                        "→ Settings → AI). It powers the AI location estimate."]

    url = (query or "").strip()
    content, ctype, err = await _download(url)
    if err:
        return [], [], [f"visual_geolocate: {err}"]
    mime = ctype if ctype.startswith("image/") else "image/jpeg"

    b64 = base64.b64encode(content).decode()
    endpoint = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{GEMINI_MODEL}:generateContent")
    body = {
        "contents": [{"parts": [
            {"text": _GEO_PROMPT},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(endpoint, params={"key": key}, json=body)
    except httpx.HTTPError as e:
        return [], [], [f"visual_geolocate: Gemini request failed: {type(e).__name__}: {e}"]
    if r.status_code != 200:
        detail = r.text[:200]
        return [], [], [f"visual_geolocate: Gemini HTTP {r.status_code}: {detail}"]

    import json
    try:
        cand = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        est = json.loads(cand)
    except Exception as e:  # noqa: BLE001
        return [], [], [f"visual_geolocate: could not parse Gemini response: {type(e).__name__}"]

    label = _img_label(url)
    img_key = f"image:{label}"
    findings: list[Finding] = [Finding(
        entity_type="image", platform="visual_geolocate", label=label, url=url,
        confidence=0.7, data={"url": url, "source": "visual_geolocate"},
    )]
    edges: list[EdgeResult] = []
    errors: list[str] = []

    if not est.get("identifiable"):
        errors.append(f"{NOTE_PREFIX}AI could not localise the image from its content"
                      + (f": {est.get('reasoning')}" if est.get("reasoning") else "."))
        return findings, edges, errors

    place = (est.get("place") or "").strip()
    country = (est.get("country") or "").strip()
    loc_label = place or country or "AI-estimated location"
    # AI estimate is a LEAD, not proof — cap the confidence hard.
    conf = min(0.55, max(0.2, float(est.get("confidence") or 0.4)))
    lat, lon = est.get("lat"), est.get("lon")
    data = {"place": place, "country": country, "lat": lat, "lon": lon,
            "confidence_ai": est.get("confidence"), "reasoning": est.get("reasoning"),
            "source": "visual_geolocate", "estimate": True,
            "evidence": "AI visual estimate — verify before use"}
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        data["osm"] = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=8/{lat}/{lon}"
    findings.append(Finding(
        entity_type="location", platform="visual_geolocate",
        label=f"{loc_label} (AI-estimate)", confidence=conf, data=data,
    ))
    edges.append(EdgeResult(from_entity=img_key,
                            to_entity=f"location:{loc_label} (AI-estimate)",
                            relation="ai_estimated_location", confidence=conf))
    return findings, edges, errors
