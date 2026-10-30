# Reports

You can turn any case into a **PDF report** — useful for the file, for
disclosure, or for briefing colleagues.

## Generating a report

1. Open the case and click **"PDF report"** in the header (this opens
   the **"Generate PDF report"** page).
2. Under **"Sections to include"**, tick the parts you want. Available
   sections, in the order they appear in the document:
   - **"Cover page"** — logo, case number, title, status
   - **Summary** — what the case contains, broken down by type
   - **Key findings** — the twenty highest-ranked findings *with the reason
     each ranks where it does*: which tools confirmed it and how the source
     rates. This is the section a reader who only reads one section should get.
   - **Entities table** — all findings, ordered by relevance rather than
     alphabetically
   - **Relationships** — who is connected to whom, grouped by type, **with the
     tool that asserted each link**
   - **Graph snapshot** — a picture of the network, with double rings marking
     findings that more than one tool reported
   - **Searches** — which searches produced this case
   - **Alerts**
   - **Timeline**
   - **Evidence** — the citation appendix: source URL, tool, and when the
     source stated it versus when it was stored

   All are pre-selected by default; untick anything you don't need.

> **The report says what it left out.** If anything in the case is marked
> relevant, the report contains exactly those findings; otherwise it contains
> everything not marked as a false positive. Either way it states which rule
> applied and how much it suppressed — a filtered report that does not say it is
> filtered would be worse than an unfiltered one. Placeholders are never counted
> as findings (see [Assessing findings](12-assessing-findings.md)).
3. The report is rendered in **your current UI language** (*"Report will
   be rendered in {language}…"*) — switch the header language selector
   first if you want a different one.
4. Click **"Generate PDF"**. The file downloads as
   `{case_number}.pdf` and you'll see **"Report downloaded"**.

If it fails you'll see *"Report generation failed"* — try again or
reduce the selected sections, and tell your operator if it persists.

## Tips

- **Mark key entities as relevant** before generating — flagged entities
  stand out in the report.
- The **cover page** uses your organisation's **logo** and display name,
  which an admin sets under **Admin → Settings**.
- Generate a fresh report whenever the case has moved on; the PDF is a
  point-in-time snapshot, not a live document.

## Report options

- **Only findings marked relevant (extract)** — tables, graph and saved pages
  show only the findings you marked ★ relevant and the links between them.
  Every page says *"Extract"*. Without the tick the report contains every
  finding except those marked as false positives.
- **PDF or Word** — Word is for further editing: same content and pictures,
  simpler layout.
- Two further sections: **"Search log"** (who searched what, when, and for
  what stated purpose) and **"Saved pages"** (screenshots with their SHA-256,
  so a reader can check a downloaded file).
- A case opened from a **template** starts with that offence type's outline.

---

Next: **[Reference & glossary →](09-reference.md)** · Back: **[Monitoring & alerts](07-monitoring-and-alerts.md)**
