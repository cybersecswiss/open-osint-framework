"""Saved pages — screenshots with their SHA-256, as an annex.

The evidence captured in the case (routers/evidence.py): each saved page with
address, time, who saved it, the hashes of screenshot and archive, and the
screenshot itself. The hash is printed next to the picture on purpose: a
reader holding the downloaded file can check it is the one shown here.

At most `MAX_IMAGES` screenshots are embedded — a case with hundreds of
captures would otherwise produce a report nobody can open; the rest are
listed with their hashes. In an extract of relevant findings only, only pages
saved for those findings (or saved by address) appear.
"""
from __future__ import annotations

import base64
from typing import Any

from app.models.case import Case
from app.services.agent_client import get_bytes_from_agent, get_from_agent
from app.services.report.base import SectionData, SectionStrings, fmt_dt, register_section

MAX_IMAGES = 20

_S = SectionStrings({
    "en": {"title": "Saved pages", "none": "No pages have been saved in this case.",
           "unavailable": "The saved pages could not be read from your authority's data store.",
           "by": "saved by", "status": "HTTP", "tor": "via Tor", "more": "{n} further saved pages are listed without image.",
           "shot": "Screenshot SHA-256", "archive": "Archive SHA-256", "redirects": "Redirects",
           "verify": "Check a downloaded file: sha256sum FILE (Windows: certutil -hashfile FILE SHA256)."},
    "de": {"title": "Gesicherte Seiten", "none": "In diesem Fall wurden keine Seiten gesichert.",
           "unavailable": "Die gesicherten Seiten konnten nicht aus dem Datenspeicher Ihrer Behörde gelesen werden.",
           "by": "gesichert durch", "status": "HTTP", "tor": "über Tor", "more": "{n} weitere gesicherte Seiten sind ohne Bild aufgeführt.",
           "shot": "SHA-256 Bildschirmfoto", "archive": "SHA-256 Archiv", "redirects": "Weiterleitungen",
           "verify": "Heruntergeladene Datei prüfen: sha256sum DATEI (Windows: certutil -hashfile DATEI SHA256)."},
    "fr": {"title": "Pages sauvegardées", "none": "Aucune page n'a été sauvegardée dans ce dossier.",
           "unavailable": "Les pages sauvegardées n'ont pas pu être lues dans le stockage de votre autorité.",
           "by": "sauvegardée par", "status": "HTTP", "tor": "via Tor", "more": "{n} autres pages sauvegardées sont listées sans image.",
           "shot": "SHA-256 capture", "archive": "SHA-256 archive", "redirects": "Redirections",
           "verify": "Vérifier un fichier téléchargé : sha256sum FICHIER (Windows : certutil -hashfile FICHIER SHA256)."},
    "it": {"title": "Pagine salvate", "none": "In questo caso non è stata salvata alcuna pagina.",
           "unavailable": "Non è stato possibile leggere le pagine salvate dall'archivio della Sua autorità.",
           "by": "salvata da", "status": "HTTP", "tor": "tramite Tor", "more": "Altre {n} pagine salvate sono elencate senza immagine.",
           "shot": "SHA-256 screenshot", "archive": "SHA-256 archivio", "redirects": "Reindirizzamenti",
           "verify": "Verificare un file scaricato: sha256sum FILE (Windows: certutil -hashfile FILE SHA256)."},
})


@register_section(name="captures", order=62, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any] | None = None,
                only_relevant: bool = False, **_kw) -> SectionData:
    try:
        items = (await get_from_agent(case.tenant, f"/api/cases/{case.id}/evidence")).get("evidence") or []
    except Exception:  # noqa: BLE001
        return SectionData(title=_S.t(lang, "title"), template="sections/captures.html",
                           context={"none_text": _S.t(lang, "unavailable"), "rows": [], "S": {}})
    if only_relevant:
        shown = {str(e.get("id")) for e in (agent_data or {}).get("entities") or []}
        items = [i for i in items if not i.get("entity_id") or i["entity_id"] in shown]
    rows = []
    for n, it in enumerate(items):
        img = None
        if n < MAX_IMAGES:
            try:
                body, _ = await get_bytes_from_agent(
                    case.tenant, f"/api/evidence/{it['id']}/screenshot?case_id={case.id}")
                img = "data:image/png;base64," + base64.b64encode(body).decode()
            except Exception:  # noqa: BLE001 — listed without picture
                img = None
        rows.append({
            "title": it.get("title") or "—", "url": it.get("final_url") or it.get("url"),
            "when": fmt_dt(it.get("captured_at")), "by": it.get("captured_by") or "—",
            "status": it.get("http_status"), "tor": it.get("via_tor"),
            "redirects": " → ".join([it.get("url") or "", *((it.get("meta") or {}).get("redirect_chain") or [])])
                         if (it.get("meta") or {}).get("redirect_chain") else None,
            "shot": it.get("screenshot_sha256"), "archive": it.get("archive_sha256"), "img": img,
        })
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/captures.html",
        context={
            "rows": rows,
            "none_text": _S.t(lang, "none") if not rows else None,
            "more": _S.t(lang, "more", n=len(rows) - MAX_IMAGES) if len(rows) > MAX_IMAGES else None,
            "S": {k: _S.t(lang, k) for k in ("by", "status", "tor", "shot", "archive", "redirects", "verify")},
        },
    )
