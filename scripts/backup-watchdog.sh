#!/bin/bash
# =====================================================================
# Did the backup chain actually run?
#
#   bash scripts/backup-watchdog.sh            # human-readable
#   bash scripts/backup-watchdog.sh --quiet    # only problems
#
# Exit code 0 = every job ran on time and succeeded. 1 = something is
# overdue or failed. Meant to be read by health-check.sh, by the operator
# console, and by a human after a reboot.
#
# ## What it actually checks
#
# Not "does a backup file exist" — a file exists long after the job that
# wrote it stopped running. Two questions instead:
#
#   * did each job finish within its expected window (age), and
#   * did it finish successfully (exit code),
#
# both from the state files scripts/run-scheduled.sh writes. Plus one
# independent cross-check that does NOT trust the state files at all: the
# newest artefact on disk. A job can report success and still produce
# nothing if it is pointed at the wrong directory.
# =====================================================================
set -uo pipefail

STATE_DIR="${OSINT_JOB_STATE_DIR:-$HOME/.osint-job-state}"
QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_RESET=$'\033[0m'
[[ -t 1 ]] || { C_GREEN=""; C_RED=""; C_YELLOW=""; C_RESET=""; }

# name : maximum age in hours before it counts as overdue.
# The grace is generous on purpose — a daily job that runs at 03:15 and is
# checked at 03:10 the next day is 23h55m old and perfectly healthy. 30h
# means "it missed a whole day", which is the thing worth waking up for.
# Jobs to watch, name:max-age-hours. Extend when you schedule more, e.g.
#   WATCH_JOBS="backup:30 dr-archive:30" bash scripts/backup-watchdog.sh
read -r -a JOBS <<<"${WATCH_JOBS:-backup:30}"

FAIL=0
NOW=$(date +%s)

report() { [[ $QUIET -eq 1 ]] || printf '%s\n' "$*"; }
problem() { printf '%s\n' "$*" >&2; FAIL=1; }

report "=== Scheduled backup jobs ==="
for entry in "${JOBS[@]}"; do
    name="${entry%%:*}"
    max_h="${entry##*:}"
    state="$STATE_DIR/$name.json"

    if [[ ! -f "$state" ]]; then
        problem "  ${C_RED}[MISSING]${C_RESET} $name — never ran (no state file).
           Either the cron entry is missing or it does not call run-scheduled.sh."
        continue
    fi

    fin=$(python3 -c "
import json,sys
try: print(int(json.load(open('$state')).get('finished_epoch',0)))
except Exception: print(0)")
    ok=$(python3 -c "
import json,sys
try: print('yes' if json.load(open('$state')).get('ok') else 'no')
except Exception: print('no')")
    rc=$(python3 -c "
import json,sys
try: print(json.load(open('$state')).get('exit_code','?'))
except Exception: print('?')")

    age_h=$(( (NOW - fin) / 3600 ))
    when=$(date -d "@$fin" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '?')

    if [[ "$ok" != "yes" ]]; then
        problem "  ${C_RED}[FAILED]${C_RESET} $name — last run $when ended with code $rc"
    elif (( age_h > max_h )); then
        problem "  ${C_RED}[OVERDUE]${C_RESET} $name — last success $when (${age_h}h ago, allowed ${max_h}h)"
    else
        report "  ${C_GREEN}[OK]${C_RESET}    $name — $when (${age_h}h ago)"
    fi
done

# --- Unabhaengige Gegenprobe -----------------------------------------
# Die Zustandsdateien sagen, was der Auftrag GEMELDET hat. Das hier sagt,
# was auf der Platte liegt. Beides zu pruefen kostet nichts und faengt
# den Fall ab, dass ein Auftrag erfolgreich in ein falsches Verzeichnis
# schreibt.
report ""
report "=== What is actually on disk ==="
check_newest() {
    local label="$1" pattern="$2" max_h="$3"
    local newest
    # -d matters: the daily backups are DIRECTORIES, and without it `ls`
    # lists their contents and the newest "file" is whatever is inside.
    newest=$(ls -1dt $pattern 2>/dev/null | head -1)
    if [[ -z "$newest" ]]; then
        problem "  ${C_RED}[EMPTY]${C_RESET} $label — nothing under $pattern"
        return
    fi
    local age_h=$(( (NOW - $(stat -c%Y "$newest")) / 3600 ))
    if (( age_h > max_h )); then
        problem "  ${C_RED}[OLD]${C_RESET} $label — newest is ${age_h}h old ($(basename "$newest"))"
    else
        report "  ${C_GREEN}[OK]${C_RESET}    $label — $(basename "$newest") (${age_h}h ago)"
    fi
}
check_newest "Daily backup" "${BACKUP_ROOT:-/var/backups/oof}/2*_*" 30
# Only when a DR archive directory is configured (DR_DIR=/path).
[[ -n "${DR_DIR:-}" ]] && check_newest "DR archive" "$DR_DIR/osint-DR-*.tar.gz" 30

report ""
if [[ $FAIL -eq 0 ]]; then
    report "${C_GREEN}All backup jobs are current and succeeded.${C_RESET}"
else
    printf '%s\n' "${C_YELLOW}At least one backup job is not running as expected.${C_RESET}" >&2
    printf '%s\n' "Log: tail -40 /var/log/oof-backup.log" >&2
fi
exit $FAIL
