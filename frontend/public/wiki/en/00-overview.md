# OSINT Platform — User Handbook

Welcome. This handbook explains how to run investigations on the OSINT
platform: logging in, creating a case, searching across data sources,
reading the relationship graph, monitoring targets over time, and
exporting reports.

It is written for **investigators** (end users). Setup, servers and
credentials are covered separately in the operator handbook
(`docs/operations.en.md`).

## Contents

1. **[Getting started](01-getting-started.md)** — logging in with your
   work email and finding your way around.
2. **[Working with cases](02-cases.md)** — every investigation lives in
   a case; how to create and manage them.
3. **[Running a search](03-searching.md)** — the core workflow: pick a
   query type, enter an indicator, choose modules, read the progress.
4. **[Modules & tools](04-modules-and-tools.md)** — the collection
   modules and every tool inside them.
5. **[Telegram tools (deep)](05-telegram.md)** — authenticated Telegram
   collection: channel scans, user / phone / geo lookups.
6. **[Reading the graph](06-reading-the-graph.md)** — how to explore the
   entities and relationships a search produces.
7. **[Assessing findings](12-assessing-findings.md)** — ratings,
   cross-confirmation, relevance and evidence: deciding which of several
   hundred results actually matter.
8. **[Tracking changes](13-tracking-changes.md)** — what a re-run added,
   and what the platform deliberately cannot tell you.
9. **[The AI function](11-ai-function.md)** — assisted linking, where it
   is licensed.
10. **[Monitoring & alerts](07-monitoring-and-alerts.md)** — watch a
    target and get notified when something changes.
11. **[Reports](08-reports.md)** — turn a case into a shareable report.
12. **[Exporting a case](14-exporting.md)** — CSV, Maltego, MISP and
    STIX for handing findings to another system or agency.
13. **[Reference & glossary](09-reference.md)** — query types, entity
    types, edge relations, and troubleshooting.
14. **[Support & tickets](10-support.md)** — reaching the operator.

## In one minute

1. Open the platform URL and sign in with your **work email**.
2. Create a **case** for your investigation.
3. Open the case and run a **search**: choose a *query type* (username,
   email, domain, IP, phone, Telegram channel, crypto address, …), type
   the indicator, tick the **modules** to run, and start.
4. Results appear as a **graph** of entities and relationships inside the
   case. Click any node for details; double-click to pivot deeper.
5. Optionally set up **monitoring** on a target, or export a **report**.

> **Your data stays yours.** Investigation data (cases, entities,
> results) is stored in your own organisation's system. The platform
> operator runs the software but cannot read your case data.

---

Start here: **[Getting started →](01-getting-started.md)**
