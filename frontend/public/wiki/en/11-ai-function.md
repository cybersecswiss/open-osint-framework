# The AI function (assisted linking)

The **AI function** is an optional, licensed helper that looks at a
case's graph and **suggests** how the pieces might connect — identity
clusters ("these accounts look like the same person"), likely
relationships between nodes, and a short narrative with next steps.

It is **assistive, never automatic**. The AI only ever proposes; *you*
decide what is true and commit the links you agree with. Nothing is
added to the case behind your back.

> **Availability.** The button only appears if your authority is
> **licensed** for the AI function. If you don't see it, it isn't enabled
> for your account — that's expected.

## Using it

1. Open a case with some findings and go to the **Network Graph** (or the
   AI panel on the case).
2. Click **"AI-Link" / "Analyse with AI"**. A job starts and runs in the
   background — you can keep working; it won't block the page.
3. When it finishes you get **suggestions**:
   - **Identity clusters** — groups of nodes the model thinks are the
     same actor.
   - **Suggested connections** — proposed edges between nodes, each with
     a short reason.
   - A brief **narrative** and **next steps** to consider.
4. **Review each suggestion.** Apply the ones you agree with (they become
   real edges in the graph, marked as `source: ai`); ignore the rest.
   Re-applying the same suggestion later is harmless — it won't duplicate.

## What the AI sees (and doesn't)

To keep case data inside your sovereign boundary as much as possible, the
platform sends the model only the **graph structure** — node types,
labels, and compact hints — and **strips sensitive values** before they
ever leave (passwords, cookies, tokens, hashes, raw banners, cleartext
credentials are never sent). Large data blobs are trimmed to short
summaries; buried identifiers (a stray email/phone/handle) are kept
because those are exactly what helps the linking.

> **Sovereignty note.** With the default cloud model (Gemini), the
> stripped-down graph does leave your infrastructure to the provider.
> That is why the feature is **licensed per authority and used with
> consent**. A fully local model is the sovereign alternative on the
> roadmap.

## Good practice

- **Treat suggestions as leads, not verdicts.** Confirm a proposed link
  against the underlying evidence before you rely on it in a report.
- **Focus the case first.** Marking the clearly-relevant nodes and
  removing false positives before running the AI gives it cleaner input
  and better suggestions.
- **Big cases:** only the most-relevant findings (a capped number, set by
  your operator) are analysed — the analysis note tells you how many of
  how many were used.

## If it doesn't run

- **"not licensed"** — the AI function isn't enabled for your authority.
- **"quota / rate-limit reached"** — the provider's usage limit was hit;
  your operator needs to raise it (enable billing) or wait for the reset.
- **"took too long"** — a very large case; your operator can lower the
  entity cap, or focus the case and retry.

These are shown as a clear message on the job, not a silent failure.

---

Next: **[Monitoring & alerts →](07-monitoring-and-alerts.md)** · Back: **[Reading the graph](06-reading-the-graph.md)**
