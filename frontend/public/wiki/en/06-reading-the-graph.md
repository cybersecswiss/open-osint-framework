# Reading the graph

The **"Network Graph"** tab draws everything in a case as a network:
**nodes** are entities (people, accounts, channels, addresses, messages,
…) and **edges** are the relationships between them. Node **colour** is
the entity type; node **size** grows with how connected it is.

## Controls (left sidebar)

- **"Layout"** — how nodes are arranged: a breadth-first tree (default),
  *Force (fcose)*, *Concentric*, *Circle*, *Grid*, or *Force (cose)*.
- **"Render cap"** — big cases can have thousands of nodes; this caps how
  many are drawn at once (100 by default, up to 1000). The badge shows
  *visible / total*.
- **"Show all labels"** — label every node instead of on hover.
- **"Filter by type"** — this is also the **legend**: a coloured entry
  per entity type with its count. Untick a type to hide it.
- **"Fit"** frames everything · **"Replay"** re-runs the layout
  animation · **"Screenshot"** downloads a PNG of the current view.
- Bottom-right **zoom** controls (buttons + slider, 10–400 %); the mouse
  wheel zooms too.

## Interacting with nodes

- **Click** a node → its **detail panel** opens on the right.
- **Double-click** a node → **"Expand search from here"**: the platform
  starts a *new* search seeded from that node (e.g. double-clicking a
  Telegram channel launches a channel search), dropping the results into
  the same case.
- **Right-click** a node → a menu: *"Show details"*, *"Expand search
  from here"*, *"Mark as relevant"* / unmark, *"Add to monitoring…"*,
  *"Remove as false positive"*, plus copy label / copy ID.
- **Hover** a node to highlight it and its connections; hover a
  highlighted edge to read its **relationship label** (e.g.
  `MEMBER_OF`, `FORWARDED_FROM`). Edges are directed (arrowheads).
- **Relevant** nodes get a gold border and halo.

Empty graph? *"No data — run a search to build the network."*

## The node detail panel

Selecting a node shows:

- Header tags: the **entity type**, the **platform** (if any), a
  **confidence** percentage, and a gold **★ relevant** tag if flagged.
- The node **label**, a clickable **URL** if present, then a table of
  every data field the source returned (URLs become links, hashes show
  with a copy button, lists render as bullets).
- Action buttons: **"Enable Monitoring"**, mark/unmark **relevant**, and
  **"Remove as false positive"**.

## Reading quality off the graph

Two visual cues carry the platform's assessment of a finding:

- **A double ring** means two or more independent tools reported this node. It is
  the strongest signal the system produces. Note that node **size** follows the
  number of connections, which makes the noisiest source visually dominant — the
  ring is the counterweight, marking the best-*supported* node rather than the
  busiest one.
- **The rating chip** (e.g. `B2`) on the node card is the Admiralty rating:
  source reliability as a letter, credibility of this particular statement as a
  digit.

Both are explained in full under [Assessing findings](12-assessing-findings.md) —
worth reading once, because the ratings change how you should prioritise.

The node card also has a **note field**. Whatever you write there stays with the
finding, travels into the report and the export, and is stored in your own
authority's database. Use it for the reasoning the rating cannot capture: why you
believe this account belongs to the same person, what you have already checked,
what still needs verifying.

## Working the case

A good rhythm: run a search → open **Findings** and work top-down (it is ordered
by relevance) → **click** interesting nodes to read details and the evidence link
→ pivot deeper with **advanced search**, so you choose what gets added → **mark
relevant** the ones that matter, **remove** the false positives, and **note** why.
Repeat until the picture is complete, then produce a [report](08-reports.md) or an
[export](14-exporting.md).

On a case you come back to, start instead with
**[New since last run](13-tracking-changes.md)**.

## Merging nodes

When two nodes are the same person or thing — two usernames of one person,
two spellings of one company — open one of them and choose **"Merge…"**. Pick
the others; they disappear into the one you opened:

- their **links** move over (a link that now exists twice becomes one, with
  both sources behind it),
- their **sources** count for the survivor, which can raise its rating,
- notes and source URL carry over, and their names stay visible as **"Also
  known as"**,
- **future searches** that find a merged name file it under the survivor
  instead of creating the node again,
- watches and alerts move to the survivor.

A merge cannot be undone and is recorded in the **"Search log"**. If you only
want to *state* a connection without deciding identity, draw a link instead.

## Same finding in other cases

If a finding of this case — an e-mail address, a username, a wallet — also
occurs in **another case of your authority**, a yellow bar above the tabs says
so, and the node card shows **"also in 2026-…"**; a click opens that case.
Only cases you are allowed to open are ever mentioned: a restricted case you
are not part of never shows up here. The comparison ignores upper/lower case
and runs in your authority's own data store.

---

Next: **[Assessing findings →](12-assessing-findings.md)** · Back: **[Telegram tools](05-telegram.md)**
