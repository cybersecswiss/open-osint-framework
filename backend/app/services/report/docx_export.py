"""Report as an editable Word document.

The same section HTML the PDF is built from, converted with `htmldocx`. Word
has no equivalent for the CSS page furniture, so the header line (authority,
case number, classification, "extract") and the classification footer are set
on the document's own header/footer instead.

Images: ONLY embedded `data:image/...` URIs are taken. `htmldocx` would
otherwise fetch every `http(s)://` image in the HTML itself, via urllib, from
inside the api container — a report containing an image URL from a finding
would make the operator's server request it (SSRF). Nothing is ever fetched
here.
"""
from __future__ import annotations

import base64
import io
import re
from typing import Any

import docx
from docx.shared import Cm, Pt, RGBColor
from htmldocx import HtmlToDocx

_DATA_URI = re.compile(r"^data:image/(png|jpe?g|gif);base64,(.+)$", re.S)


class _SafeHtmlToDocx(HtmlToDocx):
    def handle_img(self, current_attrs):
        m = _DATA_URI.match(current_attrs.get("src") or "")
        if not m:
            return                      # never fetched; silently left out
        image = io.BytesIO(base64.b64decode(m.group(2)))
        try:
            if isinstance(self.doc, docx.document.Document):
                self.doc.add_picture(image, width=Cm(16))
            else:
                self.add_image_to_cell(self.doc, image)
        except Exception:  # noqa: BLE001 — a broken picture must not cost the report
            self.doc.add_paragraph("[image]")


def html_to_docx(sections: list[dict[str, Any]], header: str, classification: str) -> bytes:
    doc = docx.Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2)
    hp = sec.header.paragraphs[0]
    hp.text = header
    for r in hp.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    if classification:
        fp = sec.footer.paragraphs[0]
        run = fp.add_run(classification)
        run.bold = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0xCF, 0x13, 0x22)

    conv = _SafeHtmlToDocx()
    for n, s in enumerate(sections):
        if n:
            doc.add_page_break()
        doc.add_heading(s.get("title") or "", level=1)
        conv.add_html_to_document(s.get("html") or "", doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
