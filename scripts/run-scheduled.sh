#!/bin/bash
# =====================================================================
# Wrapper for every scheduled job, so that a job which STOPS RUNNING is
# noticed.
#
#   run-scheduled.sh <name> <command…>
#
# ## Why this exists
#
# The backup chain was complete and correct and had one hole big enough to
# lose everything through: **nothing said when it stopped.** The only
# evidence was ~/osint-backup.log, which somebody had to think of reading.
# A cron that does not survive a reboot, a script that dies on a changed
# path, an ssh key that expires — all of them fail exactly the same way,
# silently, and are discovered on the day a backup is needed.
#
# ## Why a wrapper and not a line at the end of each script
#
# Because "write success at the end" only ever records successes. A script
# that dies at step two never reaches its own last line, so the state file
# would still show the last good run and the watchdog would see nothing
# wrong. The wrapper records the OUTCOME — including a non-zero exit and
# including a crash — because it is the thing that outlives the command.
#
# State: ~/.osint-job-state/<name>.json, read by scripts/backup-watchdog.sh
# and by scripts/health-check.sh.
# =====================================================================
set -uo pipefail

NAME="${1:-}"
shift || true
[[ -n "$NAME" && $# -gt 0 ]] || { echo "usage: $0 <name> <command…>" >&2; exit 2; }

STATE_DIR="${OSINT_JOB_STATE_DIR:-$HOME/.osint-job-state}"
mkdir -p "$STATE_DIR"
STATE="$STATE_DIR/$NAME.json"

START_EPOCH=$(date +%s)
START_ISO=$(date -Is)

# Run it. `set -e` is deliberately NOT on: the exit code is the payload
# here, not a reason to abort before recording it.
"$@"
RC=$?

END_EPOCH=$(date +%s)
DURATION=$(( END_EPOCH - START_EPOCH ))

# Written to a temp file and moved into place, so a watchdog reading
# concurrently never sees half a JSON document.
TMP="$STATE.tmp.$$"
cat > "$TMP" <<JSON
{
  "job": "$NAME",
  "started_at": "$START_ISO",
  "finished_at": "$(date -Is)",
  "finished_epoch": $END_EPOCH,
  "duration_seconds": $DURATION,
  "exit_code": $RC,
  "ok": $([[ $RC -eq 0 ]] && echo true || echo false),
  "command": "$(printf '%s ' "$@" | sed 's/"/\\"/g; s/ *$//')"
}
JSON
mv -f "$TMP" "$STATE"

if [[ $RC -ne 0 ]]; then
    echo "FEHLER: geplanter Auftrag '$NAME' endete mit Code $RC nach ${DURATION}s" >&2
fi
exit $RC
