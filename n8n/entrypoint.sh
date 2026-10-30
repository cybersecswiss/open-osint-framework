#!/bin/sh
# Auto-import + activate the bundled workflows on every start, so the
# AI-linking workflow (and the monitoring ones) survive a fresh deploy or a
# customer install without any manual n8n UI steps.
#
# Idempotent: `import:workflow` upserts by the workflow's top-level `id`.
# On a brand-new DB the import no-ops (schema not there yet — n8n creates it
# on `n8n start`); it lands on the next restart. `exec n8n start` afterwards
# registers the now-active workflows' webhooks on this same boot.
set -e

WF="${N8N_USER_FOLDER:-/home/node/.n8n}/workflows"
if [ -d "$WF" ]; then
    if n8n import:workflow --separate --input="$WF" >/tmp/import.log 2>&1; then
        echo "n8n-autoimport: imported workflows from $WF"
    else
        echo "n8n-autoimport: skipped (fresh DB / schema not ready yet — will import on next start)"
    fi
    # Activate every workflow that can actually run unattended.
    #
    # That is only ai-link and ai-news now, and they are here for one
    # reason: their prompts are meant to be edited by a human without a
    # rebuild. Everything else that used to live in n8n moved into the
    # backend — see n8n/workflows/README.md for the rule and the three
    # cases that produced it.
    #
    # ⚠️ `import:workflow` DEACTIVATES what it imports, because the bundled
    # JSON files carry `active: false`. So these two lines are not a
    # convenience — without them the AI function is dead after every single
    # restart, and the only symptom is a button that returns nothing (the
    # import log says "Deactivating workflow …" and nothing turns them back
    # on).
    n8n update:workflow --active=true --id=AiLinkGemini0001 >/dev/null 2>&1 \
        && echo "n8n-autoimport: activated ai-link" || true
    n8n update:workflow --active=true --id=AiNewsGemini0001 >/dev/null 2>&1 \
        && echo "n8n-autoimport: activated ai-news" || true

    # Three legacy workflows were REMOVED — scheduled-rescan,
    # change-detection-alert and license-expiry. The backend does all three
    # now (services/scheduler.py, services/alerting.py,
    # services/operator_notify.py); see n8n/workflows/README.md for what
    # each one got wrong.
    #
    # Deleting the files stops a FRESH install from ever importing them.
    # An installation that already has them keeps them in its n8n database,
    # where nothing here can reach them (this image's n8n CLI has no
    # `delete:workflow`). So they are forced inactive on every start: an
    # inactive duplicate is harmless, an active one consumes the schedule of
    # every due monitoring config and searches nothing.
    #
    # Removing these lines is safe once no installation still carries the
    # legacy workflows. Until then they cost one no-op each per boot.
    for legacy in SchedRescan00001 ChangeDetect0001 LicenseExpiry001; do
        if n8n update:workflow --active=false --id="$legacy" >/dev/null 2>&1; then
            echo "n8n-autoimport: legacy workflow $legacy forced INACTIVE (superseded by the backend)"
        fi
    done
fi

exec n8n start
