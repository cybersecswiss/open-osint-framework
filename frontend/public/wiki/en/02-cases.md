# Working with cases

Every investigation lives in a **case**. All search results are attached
to a case, so the first step is always to have one open.

## Creating a case

1. Go to **Cases** and click **"New Case"** (top-right).
2. Fill in:
   - **"Title"** (required) — a short name for the investigation.
   - **"Priority"** — *Normal*, *High*, or *Urgent* (default *Normal*).
3. Confirm. The case gets an automatic **case number**.

> You can also create a case on the fly from the search form with the
> **"New"** button next to *"Assign to Case"*.

A **description** isn't in the create dialog — add it later via **"Edit"**
inside the case.

## The case list

The **Cases** table shows **"Case Number"**, **"Title"**, **"Status"**,
**"Priority"**, and **"Created"**. Click a row to open it.

**Right-click** any row for quick actions: *"Open case"*, *"Copy case
number"*, *"Copy ID"*, and (admins only) *"Delete"*.

## Inside a case

The case header shows the case number, title, and status/priority tags,
plus buttons:

- **"PDF report"** — a written report on the case (see [Reports](08-reports.md)).
- **"Export"** — the same case as CSV, Maltego, MISP or STIX
  ([Exporting](14-exporting.md)).
- **"Edit"** — change title, **description**, status (*Open / In
  progress / Closed / Archived*), priority, or **"Assigned to"**.
- **"Delete"** — admins only.

Below the header are the case tabs:

1. **"Findings"** — the results as a working list, ordered by relevance
   ([how findings are assessed](12-assessing-findings.md)). This is the
   tab to start in.
2. **"Network Graph"** — the visual map of everything found
   ([how to read it](06-reading-the-graph.md)).
3. **"Map"** — every finding that carries coordinates, plotted
   geographically, with a timeline beside it. Only useful once a case
   contains located findings (places, reviews, geotagged images).
4. **"List (N)"** — the same entities as a searchable, sortable table.
5. **"New since last run"** — what the most recent search added
   ([tracking changes](13-tracking-changes.md)).
6. **"New Search"** — run a search whose results drop straight into this
   case ([how searching works](03-searching.md)).

## Tidying results

As results come in you'll want to separate signal from noise:

- **Mark as relevant** — flags a key entity (gold star + halo in the
  graph) so it stands out and appears prominently in reports.
- **"Remove as false positive"** — deletes an entity and its links from
  the case when it's clearly noise.

Both are available by right-clicking a node, from the node detail panel,
or from the **List** tab's *Actions* column.

## Search log

The tab **"Search log"** lists every search in the case: when, by whom, which
selector, and the stated **purpose / legal basis**. Automatic rescans of a
watch appear as *"Automatic rescan"*. The log lives in your authority's own
data store; the platform operator cannot read it.

## Case templates

When creating a case you can pick a **template (offence type)** — ransomware,
phishing, darknet trade, sextortion and so on. It is a starting point, not a
rule:

- the **search form** in the case preselects the matching playbook (modules),
- the **report** starts with an outline that suits the offence type,
- a blue tag in the case header names the template; hovering it lists the
  **typical next tools**, and a click opens the search.

The template can be changed or removed at any time via **Edit**.

## Restricted cases (need-to-know)

By default everyone in your authority sees every case. Switch **"Access"** on
when creating or editing a case to **restrict** it: then only the **creator**,
the **assignee**, the listed **members** and your authority's **admins** see
it. For everyone else the case does not exist — it is missing from lists,
searches, alerts and watches, and opening its link answers "not found".

- Only the person who created the case, or an admin, can change who has
  access. Members can work in the case but cannot widen the circle.
- Members are usernames. Colleagues who have never signed in can be added.
- Every change of access is recorded in the case's **"Search log"**.
- Admins are deliberately included: someone must be able to reassign a case
  whose investigator has left.

## Saving evidence

A finding is a link — if the page is deleted, only the claim remains. **"Save
page"** (in the node card of a finding that has a source page, or on the tab
**"Evidence"** for any address you type) loads the page in a real browser and
files, in your authority's own data store:

- a **full-page screenshot** (PNG),
- an **archive** of the page with its images and styling (MHTML — opens in
  Chrome or Edge),
- the **SHA-256** of each file, the final address after redirects, the HTTP
  status, the time, who saved it and whether Tor was used.

`.onion` pages are loaded over Tor and can take over a minute. Internal
addresses are refused. The SHA-256 lets anyone check later that a downloaded
file is exactly the one that was saved — on Windows:
`certutil -hashfile file.mhtml SHA256`. Every save is also recorded in the
**"Search log"**. The platform operator keeps only the hashes, never the page.

---

Next: **[Running a search →](03-searching.md)** · Back: **[Getting started](01-getting-started.md)**
