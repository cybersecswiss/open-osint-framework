# Assessing findings

A search over a dozen modules routinely returns several hundred nodes. Collecting
was never the hard part — deciding which twenty matter is. This page explains the
three mechanisms the platform gives you for that, and, just as importantly, what
each of them does **not** claim.

## The rating (Admiralty)

Every finding carries a two-character rating such as **B2**. It is the NATO
Admiralty scale, and it answers two separate questions that a single "confidence"
number used to blur together.

**The letter — how reliable is the source?** Declared per tool, because only the
tool's author knows what kind of statement it makes. A hit from a certificate
registry is a different sort of fact from a hit on a scraped profile page, even
when both "worked".

| | Meaning |
|---|---|
| **A** | Completely reliable — authoritative registry or primary record |
| **B** | Usually reliable |
| **C** | Fairly reliable |
| **D** | Not usually reliable |
| **E** | Unreliable |
| **F** | **Cannot be judged** — the tool declares nothing |

**F is an honest gap, not a bad grade.** It means nobody has assessed that source,
so you should not read it as "weak evidence" — read it as "unassessed".

**The digit — how credible is this particular statement?** Derived by the platform
per finding, because only the platform can see whether other tools agreed.

| | Meaning |
|---|---|
| **1** | Confirmed by other sources — **two or more independent tools reported the same thing** |
| **2** | Probably true |
| **3** | Possibly true |
| **4** | Doubtful |
| **6** | Cannot be judged |

**5 ("improbable") is never assigned.** Nothing in the collection pipeline can
justify actively arguing against a finding, so the platform does not pretend it
can.

One subtlety worth knowing: when several tools report the same node, the letter
shown is the **best** reliability among them. If a registry and a scraper both
return a value, the registry's word is what the finding is worth — a weak second
source can raise credibility, but it cannot lower reliability.

## Cross-confirmation

Under the rating you will see the tools that independently reported the same
finding, e.g. **✓ 3**. Hover to see which ones.

This is the strongest signal the system produces, and it is the reason the digit
can ever reach **1**. Two properties make it trustworthy:

* It is keyed on the **canonical identity** of the finding, not on the exact
  spelling — two ways of writing the same address still count as agreement.
* It **accumulates across searches**. A tool confirming a node months later is
  added to the list rather than replacing it. That history is exactly the part
  worth keeping.

In the graph, a node that two or more independent tools reported is drawn with a
**double ring**. Node size follows how many connections a node has, which makes
the loudest source visually dominant; the ring is the counterweight, marking the
best-supported finding rather than the busiest one.

## Relevance ranking

The findings list is ordered by a relevance score built from four signals:

| Signal | Weight | Why |
|---|---|---|
| Cross-confirmation | 40 % | Independent agreement is the hardest signal to fake |
| Source reliability | 25 % | The Admiralty letter |
| Position in the graph | 20 % | How connected the node is |
| Distance from your selector | 15 % | Hops from what you actually searched for |

The score is **calculated fresh every time, never stored**. Mark a false positive
or run another tool and the order changes immediately. A stored column would be
stale from the next click onwards, and you would have no way of telling which rows
were current.

The report uses the same score in the same way, so the order you see on screen is
the order the PDF argues in. There is deliberately only one ranking in the system.

## Evidence

Where a tool reported a source, the finding carries an **evidence link** — the
page the statement came from — plus the time the source stated it (`observed`) as
distinct from the time it was stored in your case (`found`). For fast-moving
sources such as leak sites, pastes and Telegram, the observation time is the one
that matters evidentially.

> **Older findings may have no evidence link.** A column can only be filled by a
> tool that returns the value, so rows collected before your instance gained
> provenance support stay empty until that source is scanned again. This is a gap
> in the record, not an error in the finding — and re-running the search fills it
> in without creating duplicates.

## Placeholders are not findings

Some nodes exist only to keep the graph connected: a relationship was reported
whose other end was never itself confirmed. These are marked as placeholders,
they are counted separately, and they never appear in reports or exports. Nobody
asserted them, so they are not evidence of anything.

The one exception is the node for the term you searched for. It is technically
virtual, but it is the selector under investigation and it anchors most of the
graph, so it is treated as real throughout.

## What to do with all this

A practical order of work:

1. Sort by relevance (the default) and read the top of the list first.
2. Prefer findings with a **digit of 1** — those are the ones more than one tool
   stands behind.
3. Open the evidence link before you rely on anything. The rating tells you how
   much weight a source deserves; it never tells you the finding is true.
4. Mark what matters as relevant (the star) and mark false positives as such.
   Both feed straight back into the ranking and into what the report contains.
5. Write down *why* in the note field on the node. The rating is the platform's
   assessment; the note is yours, and it is the one that will still make sense in
   six months.

See also: [Reading the graph](06-reading-the-graph.md) ·
[Reports](08-reports.md) · [Exporting](14-exporting.md)
