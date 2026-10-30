import hashlib
import io
import logging
import os

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    _PIL = True
except Exception:
    _PIL = False

try:
    import imagehash
    _IMAGEHASH = True
except Exception:
    _IMAGEHASH = False


def _max_bytes() -> int:
    return int(os.getenv("MAX_MEDIA_BYTES", str(20 * 1024 * 1024)))


def _gps_to_decimal(value, ref) -> float | None:
    try:
        d, m, s = value
        result = float(d) + float(m) / 60.0 + float(s) / 3600.0
        if ref in ("S", "W"):
            result = -result
        return round(result, 6)
    except Exception:
        return None


def _extract_exif(img) -> dict:
    out = {}
    try:
        raw = img._getexif()
    except Exception:
        raw = None
    if not raw:
        return out
    gps_raw = {}
    for tag_id, val in raw.items():
        tag = TAGS.get(tag_id, tag_id)
        if tag == "GPSInfo":
            for gk, gv in val.items():
                gps_raw[GPSTAGS.get(gk, gk)] = gv
            continue
        if tag in ("Make", "Model", "DateTime", "DateTimeOriginal", "Software"):
            try:
                out[tag] = str(val)
            except Exception:
                pass
    lat = _gps_to_decimal(gps_raw.get("GPSLatitude"), gps_raw.get("GPSLatitudeRef"))
    lon = _gps_to_decimal(gps_raw.get("GPSLongitude"), gps_raw.get("GPSLongitudeRef"))
    if lat is not None and lon is not None:
        out["gps"] = {"lat": lat, "long": lon}
    return out


def hash_bytes(data: bytes) -> dict:
    result = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    if _PIL:
        try:
            img = Image.open(io.BytesIO(data))
            if _IMAGEHASH:
                result["phash"] = str(imagehash.phash(img))
            exif = _extract_exif(img)
            if exif:
                result["exif"] = exif
        except Exception:
            pass
    return result


async def hash_media(client, message) -> dict | None:
    media = getattr(message, "media", None)
    if media is None:
        return None
    doc = getattr(media, "document", None)
    size = getattr(doc, "size", None) if doc is not None else None
    if size and size > _max_bytes():
        return {"hash_status": "skipped_too_large", "size_bytes": size}
    try:
        data = await client.download_media(message, file=bytes)
    except Exception as e:
        logger.warning("Media download failed for message %s: %s", getattr(message, "id", None), e)
        return {"hash_status": "download_failed"}
    if not data:
        return None
    return hash_bytes(data)
