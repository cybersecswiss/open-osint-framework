# Monitoring & alerts

Monitoring **re-runs the search for an entity at a fixed interval** and
raises an alert for what has been added since the previous run.

## Creating a watch

**Recommended:** in a case, open the entity (node card or right-click in the
graph) → **"Enable Monitoring"**. The dialog is pre-filled with that entity.
**Alternative:** **Monitoring** → **"New monitoring"**, then pick the case and
the entity.

In the dialog:

- **Purpose / legal basis** — why this selector is watched; required if your
  authority demands it (see [Running a search](03-searching.md)).
- **Interval** — *Hourly*, *Daily* (default), *Weekly* or *Monthly*.
- **"Alert on"** — *New finding in the case*, *New account, profile or
  identifier*, *New connection of the watched entity*. No selection means
  every change.
- **Alert email / webhook** — optional per watch; the authority-wide channel
  is set by your admins under **Admin → Alerting**.

The **first run is deliberately silent**: it records what is already there,
so you are only told about what appears afterwards.

## Alerts

New alerts appear on the **Dashboard** ("Unread alerts") and on the
**Alerts** page across all cases: unread first, select several to mark them
read, **"Open the case"** jumps straight to the finding. If your admins set up
e-mail or a webhook, alerts are also delivered there.

Only changes the platform can actually detect are offered. It keeps no
earlier state of a profile and cannot tell a deleted profile from a failed
lookup — so "profile changed" or "account deleted" are not triggers. Older
watches that used them show a note and keep working with the remaining ones.

## Managing watches

The **Monitoring** list shows each watch's entity, interval, status and next
run. **"Configure"** opens it: switch it **Active / Inactive**, change interval,
triggers and delivery, then **"Save"**. Automatic re-runs appear in the case's
**"Search log"**.

---

Next: **[Reports →](08-reports.md)** · Back: **[Reading the graph](06-reading-the-graph.md)**
