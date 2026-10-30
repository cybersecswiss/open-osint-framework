# Running a search

Searching is the core workflow: you give the platform an **indicator**
(a username, email, domain, IP, phone, crypto address, Telegram handle,
…), it runs the relevant **modules**, and the results build up the
case graph.

You can search from the **Search** page or from the **"New Search"** tab
inside a case. Inside a case the results refresh the graph in place;
from the standalone page you get a bookmarkable progress URL.

## Where to start: the "Lagebild" page

If you do not yet have a selector, open **Lagebild** in the menu. It lists
fields of crime taken from public situation reports — fedpol's annual
report, the NDB's *Sicherheit Schweiz*, Europol — each card naming its
source and date.

Click **"Übernehmen"** on a topic and the search form opens prefilled with
the term and sensible narrowing (e.g. *Rockerkriminalität* + *Schweiz*).
Nothing runs until you press **Start Search** — you can change the term,
the narrowing and the modules first.

> **What the catalogue is, and is not.** It describes *fields of crime*, not
> suspects. It names no organisation as a threat and establishes no
> suspicion; every statement belongs to the cited source, not to this tool.
> The entries are research starting points.

The catalogue is a file (`threat-catalog/catalog.json`) that your
administrators can extend or correct at any time — no software update
needed. Ask them if a field of crime relevant to your work is missing.

## Step by step

1. **"Search term / Indicator"** — type the thing you're investigating.
   The placeholder shows the idea: *"e.g. anonymous99,
   max@example.com, 1.2.3.4, example.com, sha256:…"*.
2. **"Type"** — choose how that term should be interpreted (Username,
   Email, Domain, IP, URL, Hash, Phone, Bitcoin/Ethereum address, the
   Telegram types, Discord invite, **Image URL**, Phone, or Keyword).
   This is the key choice — it decides which modules can run. See the
   full list in [Reference](09-reference.md#query-types).
3. **"Assign to Case"** — pick the case (or click **"New"** to make one).
   Inside a case this is already set.
4. **"Modules"** — tick the collectors to run. **Only modules that
   understand your chosen type are shown**, and they're auto-selected
   when you change the type. Hover a module to see which of its tools
   will run. If nothing supports the type you'll see *"No modules
   available for type …"*.
5. Click **"Start Search"** (it changes to *"Search running…"*).

### Playbooks — starting from the offence instead of the module list

Above the module checkboxes you will find **playbooks**: presets for common
offence types — ransomware, phishing, darknet trade, fraud / fake shop, crypto
fraud, sextortion, infrastructure. Picking one ticks the modules that are worth
running for that kind of case.

They are pure configuration: a playbook does nothing you could not do by hand,
it just spares you deciding which of a dozen modules earn their runtime. Two
details make them safe to trust:

* You only see playbooks your authority is licensed for — a preset can never
  offer a module that would then be refused.
* Each entry tells you whether it fits the **type** you have currently typed,
  so a preset built for domains is not offered for a username.

You can adjust the ticks afterwards. The playbook is a starting point, not a
setting.

## Advanced search: look before you commit

The ordinary search adds everything it finds to the case. That is what you want
when you are opening a lead, and the wrong thing when you are following one — a
single broad pivot can bury a case in noise.

**Advanced search** (the *Erweiterte Suche* drawer, also reachable from any node
in the graph) runs the same collection but **stores nothing**. You get the
candidates as a preview, with the ones already in your case flagged, and you tick
the ones to keep. Only those are written.

This is deliberate, and not only for tidiness: **the decision to link one finding
to another is made by a person.** The platform will show you that a username
appears on eleven sites; it will not decide on your behalf that they are the same
individual. In a case file, that distinction is the one that has to hold up.

Use it whenever you pivot from a finding rather than from a fresh selector —
which, after the first search, is most of the time.

> **Optional fields.** *"Email (optional)"*, *"Phone (optional)"*,
> *"Priority (optional)"* and *"Note (optional)"* are conveniences: the
> note is appended to the case description with a timestamp and your
> name. The search itself uses only the main *"Search term"* field.

## Narrowing a keyword search ("Eingrenzen")

A term like **Crimson Wolves** returns hits from all over the world. When the
search type is **Stichwort / keyword**, a field **"Eingrenzen"** appears in
which you can pick — or freely type — narrowing terms:

* **Region** — Schweiz, Deutschschweiz, Romandie, Ticino
* **Kanton** — all 26, under their official names (Zürich, Genève, Ticino …)
* **International** — Europa, International, neighbouring countries
* **Deliktsfeld** — Drogenhandel, Waffenhandel, Geldwäscherei …
* **anything you type yourself** — a city, a district, a milieu

Each narrowing term starts **one additional search run** with that term
appended. "Crimson Wolves" plus "Schweiz" and "Zürich" runs three searches:
the bare term, `Crimson Wolves Schweiz` and `Crimson Wolves Zürich`. The field
shows how many runs your selection will cost *before* you start.

All results land in the **same case**. In the graph you will see the base
term branching into the narrowed ones, so you can tell **which narrowing
produced which hit**. Services found by more than one run appear once, not
several times.

> **Why the limit of five?** Every run queries every tool of every selected
> module. Five narrowing terms across four tools are already two dozen
> requests, and several sources rate-limit us at that volume. Few, well
> chosen narrowing terms give better results than many broad ones.

> Narrowing only applies to **keyword** searches. Appending "Zürich" to an
> e-mail address or a Bitcoin address would produce a selector that matches
> nothing, so the field is hidden for those types.

## Purpose / legal basis

The field **"Purpose / legal basis"** records why a search is run — a file
number, an order, an assignment. It is stored **only in your authority's
search log** (tab **"Search log"** in the case), never with the platform
operator; the operator only learns *that* a purpose was given.

- Within a case, the last purpose you used is suggested again.
- If your administrator switched on *"Require a purpose for every search"*
  (Admin → Settings), a search without one is refused. If your authority's
  search log is unreachable at that moment, the search is **not started** —
  a search that cannot be recorded does not run.
- The same applies when you create a **watch**; its automatic rescans refer
  back to the purpose given at creation.

## Watching progress

The search fans out to every matching tool **in parallel**. A live
**"Tool status"** table updates every 3 seconds with one row per tool:

**Module · Tool · Status · Findings · Edges · Duration · Errors**

It ends as **"Completed"**, **"Completed (partial)"** (some tool hit an
error — e.g. a missing API key), **"Search failed"**, or **"Cancelled"**
(you stopped it — see below). On the standalone progress page you also get
**"Entities discovered"** and **"Connections"** counts and an **"Open
case"** button.

### Stopping a search

If a search is taking too long, or you typed the wrong selector, stop it
from the progress page with **"Stop search"**.

> **Everything found so far stays.** Findings are written to the case as
> they arrive — stopping only ends the tools that are still running. The
> progress bar therefore stays where the search actually got to and
> deliberately does **not** show 100 %: "cancelled" is not "completed", and
> a case file has to keep that difference readable.
>
> **A tool may run on briefly.** Stopping ends our wait for the source; the
> module notices at its next step. That is harmless — anything arriving
> afterwards belongs to a finished search and is no longer taken in.

> **The progress bar reflects real work** — it fills as each tool
> finishes (e.g. *7 of 11 tools done*), not a fixed guess.
>
> **Results save as they arrive.** Findings are written to the case
> **progressively, per module** — the graph fills in during the search,
> you don't have to wait for the slowest tool.
>
> **You can leave.** The search runs on the server, so switching tabs,
> navigating away, or **refreshing the browser** doesn't stop it or lose
> the progress — reopen the case (or the progress URL) and it's still
> there, updating.

> **A tool with a "key not set" note isn't a failure** — that single
> source just needs an API key your operator hasn't configured. Every
> other tool still ran. Likewise, **zero results is a valid answer**
> (e.g. an email that appears in no breach).

## What you get

Each finding becomes an **entity** (a node) in the case, and
relationships between them become **edges**. Successful modules persist
their results even if another module errored. Head to the **"Network
Graph"** tab to explore what came back.

## News & RSS

**News & RSS** in the menu is the ordinary search with the news module
preselected. It performs a full-text search across the feeds your operator
maintains — federal bodies, police, media and cyber sources — and returns
each hit as a node carrying **date, source and source kind**.

The source kind matters when you read the graph: an `authority` release and
a `media` article are both legitimate leads, but they do not carry the same
evidentiary weight. Official sources are also given a higher confidence.

Narrowing works here too, so *Rockerkriminalität* + *Schweiz* searches the
feeds for both terms together. And because the news module reacts to plain
keywords, a topic taken from the **Lagebild** page searches the news
sources as well, without any extra step.

> **What it does not do.** It searches the entries a feed publishes —
> headline and teaser — not the full text of linked PDFs. Feeds also reach
> back only as far as the source publishes them (typically a few years).
> A missing hit means "not in these feeds", never "did not happen".

Missing a source? Your operator adds it under **Settings → RSS feeds** in
the Global Admin console; it applies to the next search.

---

Next: **[Modules & tools →](04-modules-and-tools.md)** · Back: **[Working with cases](02-cases.md)**
