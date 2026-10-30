# Tracking changes on a running case

On a case that stays open for weeks, the question is rarely "what do we have" —
it is **"what is new since last time"**. Two features answer that: the *New since
last run* tab for a search you started yourself, and monitoring for the ones that
run on their own.

## "New since last run"

Open a case and choose the **New since last run** tab. It shows what the most
recent search added: new findings, new relationships, and which run they came
from.

The tab exists because re-running a search is deliberately *idempotent* — a
finding that was already in the case keeps its identity instead of being added
twice. That is the right behaviour, and it is also why a re-scan looks like
nothing happened. This view is where the difference becomes visible.

**What counts as new.** The boundary is the moment the search started; anything
stored in your case after that point is an addition. A finding that already
existed and was merely re-confirmed does **not** appear. That matters more than it
sounds: every re-scan updates provenance on existing findings, and counting those
as discoveries would make each run look like a breakthrough.

### What it does not tell you

**Disappearances are not tracked, and the view says so.**

If a leak-site entry vanishes or a profile is deleted, that will not show up here.
The reason is honest rather than technical: a tool that simply failed and a
genuine takedown look identical from inside the platform. Reporting the second
when it was in fact the first would be worse than saying nothing — so the platform
says nothing, out loud.

If a disappearance matters to your case, the sound method is the same as it has
always been: preserve the evidence when you see it (screenshot, export, evidence
link) rather than expecting the tool to notice its absence later.

## Monitoring

Where the delta view answers "what did my last run add", monitoring answers "tell
me when something changes while I am not looking".

Set a monitor on a case and the platform re-runs the search on a schedule and
raises an alert when the result changes. Set up and management are described in
[Monitoring & alerts](07-monitoring-and-alerts.md).

The two work well together: monitoring tells you *that* something moved, the
delta view shows you *what*.

## A practical routine

For a case under active investigation:

1. Re-run the search, or let the monitor do it.
2. Open **New since last run** — it is the shortest path to what changed.
3. Work through the additions top-down; they are ordered by the same relevance
   score as everywhere else (see [Assessing findings](12-assessing-findings.md)).
4. Mark the ones that matter, note why, and let the rest sit — they stay in the
   case and cost nothing.
5. Generate a report when you need a snapshot. The report always describes the
   case as it stands, not just the delta.

> **Re-running an old case is worth doing once for its own sake.** Findings
> collected before your instance gained ratings and evidence links stay unrated
> until their source is asked again. A single re-scan fills those in — without
> creating duplicates, because identity is stable.
