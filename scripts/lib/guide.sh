# shellcheck shell=bash
# =====================================================================
# guide.sh — shared look and behaviour of every install/update script.
#
# An installer is read once, under pressure, by somebody who has never
# seen it. So every script that sources this file behaves the same way:
#
#   * Every step is numbered out of a known total.
#   * A question shows its default and refuses an empty answer for
#     something that has none.
#   * A check prints ✓/✗ on its own line and never aborts by itself.
#   * `fail` exits. There is no "warn and hope" for a precondition.
#   * Two languages. `L "english" "deutsch"` prints the one selected by
#     SW_LANG (en|de). Pick it with --lang or the first question.
#
# NOTE: data-agent/install.sh and data-agent/update.sh inline a copy of
# this block, because they must run from a single download on a bare
# machine. Keep them in step.
# =====================================================================

if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'; C_CYAN=$'\033[1;36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_BLUE=''; C_GREEN=''
    C_YELLOW=''; C_RED=''; C_CYAN=''
fi

GUIDE_STEP=0
GUIDE_TOTAL="${GUIDE_TOTAL:-0}"
GUIDE_FAILED=0
SW_LANG="${SW_LANG:-en}"
# ASSUME_YES=1: every confirm() takes its default, every ask() with a
# default takes it. ask() without a default still fails — unattended runs
# must pass those values as flags.
ASSUME_YES="${ASSUME_YES:-0}"

# L "english" "deutsch" → the text in the selected language
L() { if [[ "$SW_LANG" == "de" ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

banner() {
    printf '\n%s══════════════════════════════════════════════════════════════════%s\n' "$C_BLUE" "$C_RESET"
    printf '  %s%s%s\n' "$C_BOLD" "$1" "$C_RESET"
    [[ -n "${2:-}" ]] && printf '  %s%s%s\n' "$C_DIM" "$2" "$C_RESET"
    printf '%s══════════════════════════════════════════════════════════════════%s\n\n' "$C_BLUE" "$C_RESET"
}

step() {
    GUIDE_STEP=$((GUIDE_STEP + 1))
    printf '\n%s──[ %s %d/%d ]── %s%s%s\n' \
        "$C_CYAN" "$(L Step Schritt)" "$GUIDE_STEP" "$GUIDE_TOTAL" "$C_BOLD" "$1" "$C_RESET"
}

info() { printf '   %s\n' "$*"; }
note() { printf '   %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()   { printf '   %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '   %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() {
    printf '\n   %s✗ %s%s %s\n\n' "$C_RED" "$(L STOPPED ABGEBROCHEN)" "$C_RESET" "$*" >&2
    exit 1
}

# check "label" command...  → prints ✓/✗, counts failures, ALWAYS returns 0.
# The zero matters: these scripts run under `set -e`, and a check that
# returned 1 would end the installer in its final verification — right
# before the credentials are printed.
check() {
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '   %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$label"
    else
        printf '   %s✗%s %s\n' "$C_RED" "$C_RESET" "$label"
        GUIDE_FAILED=$((GUIDE_FAILED + 1))
    fi
    return 0
}

# ask VAR "Question" ["default"]
ask() {
    local __var="$1" prompt="$2" default="${3:-}" answer=""
    if [[ "$ASSUME_YES" == "1" ]]; then
        [[ -n "$default" ]] || fail "$(L "No value for" "Kein Wert für"): $prompt"
        printf '   %s?%s %s: %s\n' "$C_YELLOW" "$C_RESET" "$prompt" "$default" >&2
        printf -v "$__var" '%s' "$default"; return 0
    fi
    while true; do
        if [[ -n "$default" ]]; then
            printf '   %s?%s %s [%s]: ' "$C_YELLOW" "$C_RESET" "$prompt" "$default" >&2
        else
            printf '   %s?%s %s: ' "$C_YELLOW" "$C_RESET" "$prompt" >&2
        fi
        read -r answer || fail "$(L "No input (stdin closed). Use --yes and flags for unattended runs." "Keine Eingabe (stdin geschlossen). Für unbeaufsichtigte Läufe --yes und Optionen verwenden.")"
        answer="${answer:-$default}"
        [[ -n "$answer" ]] && break
        printf '     %s%s%s\n' "$C_RED" "$(L "This one is required." "Diese Angabe ist Pflicht.")" "$C_RESET" >&2
    done
    printf -v "$__var" '%s' "$answer"
}

# choose VAR "Question" default option1 option2 ...  (options are literal values)
choose() {
    local __var="$1" prompt="$2" default="$3"; shift 3
    local opts=("$@") answer=""
    while true; do
        ask answer "$prompt ($(IFS=/; echo "${opts[*]}"))" "$default"
        for o in "${opts[@]}"; do
            if [[ "$answer" == "$o" ]]; then printf -v "$__var" '%s' "$o"; return 0; fi
        done
        [[ "$ASSUME_YES" == "1" ]] && fail "$(L "Invalid value" "Ungültiger Wert"): $answer"
        printf '     %s%s%s\n' "$C_RED" "$(L "Please pick one of the listed values." "Bitte einen der genannten Werte wählen.")" "$C_RESET" >&2
    done
}

# confirm "Question" [Y|N]  → 0 = yes
confirm() {
    local prompt="$1" default="${2:-N}" answer=""
    local hint; hint="$(L "[y/N]" "[j/N]")"; [[ "$default" == "Y" ]] && hint="$(L "[Y/n]" "[J/n]")"
    if [[ "$ASSUME_YES" == "1" ]]; then
        printf '   %s?%s %s %s %s\n' "$C_YELLOW" "$C_RESET" "$prompt" "$hint" "$default" >&2
        [[ "$default" == "Y" ]]; return
    fi
    printf '   %s?%s %s %s: ' "$C_YELLOW" "$C_RESET" "$prompt" "$hint" >&2
    read -r answer || answer=""
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[yYjJ]$ ]]
}

# A value the reader must write down. Aligned so it survives a screenshot.
secret_line() { printf '   %s%-34s%s %s\n' "$C_BOLD" "$1" "$C_RESET" "$2"; }

summary_ok()  { printf '\n%s══ %s ══%s\n\n' "$C_GREEN" "$1" "$C_RESET"; }
summary_bad() { printf '\n%s══ %s ══%s\n\n' "$C_RED" "$1" "$C_RESET"; }
