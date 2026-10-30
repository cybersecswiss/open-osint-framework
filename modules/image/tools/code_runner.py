"""Machine-readable codes in an image — QR, DataMatrix, Aztec, barcodes.

An image is not only a picture in a cybercrime case; it is often a container
for a selector nobody typed out. The concrete cases this answers:

* a payment QR in a sextortion or fake-invoice letter → the wallet address,
* a QR on a phishing poster or parcel-locker sticker → the landing URL,
* a QR in a forum signature or vendor banner → a Telegram handle or onion,
* a ransom-note screenshot → the payment URL the note points at,
* a shipping barcode on a seizure photo → the tracking number.

Borrowed from AIL's "decoded files" idea, which extracts QR/barcode content
and feeds it back through the same processing. That re-feeding is the part
that matters: a QR carrying `bitcoin:bc1q…` should arrive as a **btc_address
node the crypto module can run**, not as a string in a data blob that an
investigator has to notice and retype.

**Only typed selectors are emitted.** Free text inside a code is kept on the
code's own node and never turned into a `keyword` node — a QR containing a
menu, a WLAN password or a serial number would otherwise put junk in the
graph, and this tool is used precisely where an analyst cannot see the
content beforehand.

zxing-cpp was chosen over pyzbar and OpenCV: 2 MB, no system packages, and it
reads DataMatrix and Aztec as well — both of which turn up on parcels and
tickets, which pyzbar does not read.
"""
from __future__ import annotations

import io
import logging
import re
from urllib.parse import unquote, urlparse

from PIL import Image
from schemas import EdgeResult, Finding, NOTE_PREFIX

from tools.image_runner import _download, _img_label

log = logging.getLogger("module-image.codes")

MAX_CODES = 20
MAX_PAYLOAD = 2000

ONION_RE = re.compile(r"\b([a-z2-7]{56}|[a-z2-7]{16})\.onion\b", re.I)
BTC_RE = re.compile(r"\b(?:bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TG_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]{3,32})", re.I)


def _selectors(payload: str) -> list[tuple[str, str, str]]:
    """(entity_type, label, relation) for everything typed inside a payload.

    Order matters the same way it does in the browser extractor: a Telegram
    link is claimed before the generic URL rule, an onion host before the
    plain domain, so one code does not produce the same lead in two shapes.
    """
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(etype: str, label: str, rel: str) -> None:
        label = (label or "").strip()
        if not label or (etype, label.lower()) in seen:
            return
        seen.add((etype, label.lower()))
        out.append((etype, label, rel))

    scheme = payload.split(":", 1)[0].lower() if ":" in payload else ""

    # Payment URIs: `bitcoin:ADDR?amount=…`, `ethereum:0x…@1`
    if scheme in ("bitcoin", "bitcoincash", "litecoin"):
        m = BTC_RE.search(payload)
        if m:
            add("btc_address", m.group(0), "payment_address")
    if scheme == "ethereum":
        m = ETH_RE.search(payload)
        if m:
            add("eth_address", m.group(0), "payment_address")
    if scheme == "mailto":
        m = EMAIL_RE.search(unquote(payload))
        if m:
            add("email_address", m.group(0), "contact_in_code")
    if scheme in ("tel", "sms", "smsto"):
        digits = re.sub(r"[^\d+]", "", payload.split(":", 1)[1].split("?")[0])
        if re.fullmatch(r"\+?\d{8,15}", digits):
            add("phone", digits, "contact_in_code")

    for m in TG_RE.finditer(payload):
        add("telegram_channel", m.group(1), "links_to")

    for m in ONION_RE.finditer(payload):
        add("onion_service", m.group(0).lower(), "links_to")

    if scheme in ("http", "https"):
        host = (urlparse(payload).hostname or "").lower()
        # A t.me or onion link is already claimed above; re-emitting the URL
        # would hand the analyst the same lead twice.
        if not TG_RE.search(payload) and not host.endswith(".onion"):
            add("url", payload[:500], "links_to")
            if host and not host.replace(".", "").isdigit():
                add("domain", host, "links_to")

    # Bare values, for codes that carry no scheme at all.
    if not scheme:
        for m in BTC_RE.finditer(payload):
            add("btc_address", m.group(0), "payment_address")
        for m in ETH_RE.finditer(payload):
            add("eth_address", m.group(0), "payment_address")
        for m in EMAIL_RE.finditer(payload):
            add("email_address", m.group(0), "contact_in_code")

    return out


async def run_code_scan(
    query: str, query_type: str = "image_url", job_id: str = "adhoc"
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    url = (query or "").strip()
    # Reuses image_runner._download, which validates the URL before any
    # socket opens — the SSRF guard documented there applies here unchanged.
    content, ctype, err = await _download(url)
    if err:
        return [], [], [f"code_scan: {err}"]
    if ctype and not (ctype.startswith("image/") or ctype == "application/octet-stream"):
        return [], [], [f"code_scan: URL is not an image (content-type: {ctype})."]

    try:
        import zxingcpp
        img = Image.open(io.BytesIO(content))
        # zxing reads greyscale/RGB; palette and CMYK images must be converted
        # or the decoder sees noise.
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        results = zxingcpp.read_barcodes(img)
    except Exception as e:  # noqa: BLE001
        return [], [], [f"code_scan: could not decode the image ({type(e).__name__})"]

    if not results:
        return [], [], [f"{NOTE_PREFIX}No machine-readable code found in this "
                        f"image."]

    img_label = _img_label(url)
    img_key = f"image:{img_label}"
    findings: list[Finding] = [Finding(
        entity_type="image", platform="code_scan", label=img_label, url=url,
        confidence=0.9,
        data={"url": url, "source": "code_scan", "codes": len(results)},
    )]
    edges: list[EdgeResult] = []
    notes: list[str] = []

    for res in results[:MAX_CODES]:
        payload = (res.text or "").strip()
        if not payload:
            continue
        fmt = str(res.format).replace("BarcodeFormat.", "")
        code_label = payload[:120]
        findings.append(Finding(
            entity_type="machine_code",
            platform="code_scan",
            label=code_label,
            url=payload[:500] if payload.lower().startswith(("http://", "https://")) else None,
            # The code itself is a hard read: the decoder either recovers the
            # error-corrected payload or it does not. What the payload MEANS
            # is another question, and that is what the typed nodes below are
            # for.
            confidence=0.9,
            data={
                "format": fmt,
                "payload": payload[:MAX_PAYLOAD],
                "truncated": len(payload) > MAX_PAYLOAD,
                "source": "code_scan",
                "evidence": f"{fmt} decoded from the image",
            },
        ))
        edges.append(EdgeResult(
            from_entity=img_key, to_entity=f"machine_code:{code_label}",
            relation="contains_code", confidence=0.9,
        ))

        for etype, label, rel in _selectors(payload):
            findings.append(Finding(
                entity_type=etype, platform="code_scan", label=label,
                url=label if etype == "url" else None,
                confidence=0.85,
                data={"source": "code_scan", "code_format": fmt,
                      "evidence": f"read out of a {fmt} in the image"},
            ))
            edges.append(EdgeResult(
                from_entity=f"machine_code:{code_label}",
                to_entity=f"{etype}:{label}",
                relation=rel, confidence=0.85,
            ))

    if len(results) > MAX_CODES:
        notes.append(NOTE_PREFIX + f"{len(results) - MAX_CODES} further codes in "
                                   f"this image not shown (showing {MAX_CODES}).")
    return findings, edges, notes
