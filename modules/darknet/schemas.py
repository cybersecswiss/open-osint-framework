"""
Standard request/response shape and self-describing manifest for every
OSINT module.

Each module's Dockerfile copies this file into its build context so the
modules don't share a Python package via volume mount.

⚠️  Syncing this file into the modules is NOT a blind `cp`. Most modules keep
a byte-identical copy, but **module-telegram appends its own option models**
(`ScanOptions`, `UserLookupOptions`, `PhoneLookupOptions`) below the shared
contract. Overwriting its copy wholesale breaks that module's import at
startup and it restart-loops. When this file changes, splice the changed
section into the telegram copy instead of replacing it, and check with:

    for m in modules/*/; do diff -q modules/base/schemas.py "$m/schemas.py"; done

The manifest is the source of truth for what a module advertises to
the framework. Backend startup hits `/manifest` on every registered
module URL, caches the response, and the orchestrator + the public
`/api/v1/modules` endpoint render the result. Adding a new tool to a
module is a one-line manifest change — no orchestrator/frontend edits.
"""
import os
import time
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


def credential(options: "dict | None", name: str) -> str:
    """Resolve an API key for a runner. The framework passes the
    operator-global keys (managed in the Global-Admin Settings tab) in the
    /run request under `options.credentials`; that wins, and the module's
    own .env value is the fallback. Returns "" if neither is set."""
    val = ((options or {}).get("credentials") or {}).get(name)
    if val and str(val).strip():
        return str(val).strip()
    return os.environ.get(name, "").strip()

# Marker for an informational message that a runner puts in its `errors`
# list. `make_run_response` moves these into the response's `notes` field
# and — crucially — does NOT let them flip the status to "partial"/"error".
# Use for benign notices (result caps, false-positives filtered) that
# should be surfaced to the investigator but are not tool failures.
NOTE_PREFIX = "[note] "


# --- Run protocol ----------------------------------------------------

class RunRequest(BaseModel):
    job_id: str
    tool: str
    query: str
    query_type: str
    options: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    entity_type: str
    platform: Optional[str] = None
    label: str
    url: Optional[str] = None
    confidence: float = 0.8
    data: dict[str, Any] = Field(default_factory=dict)
    # When the SOURCE says this was true — not when we looked.
    #
    # Defaulting this to utcnow() is the trap: almost no runner overrides it,
    # so every entity would carry the run time in `observed_at`, a field
    # ARCHITECTURE.md calls "the evidentiary one" for fast-moving sources, and
    # a chronology built on it would show nearly every event at "when I
    # searched".
    #
    # None now means UNKNOWN, which is the honest answer for a runner whose
    # source publishes no date — same rule as `reliability`'s F and
    # `latency_class`'s medium. A runner that DOES know (an RSS publication
    # date, a breach date, a leak-site posting date, an NVD publication)
    # should set it; the framework stores NULL otherwise and the timeline
    # leaves those findings out rather than inventing a position for them.
    found_at: datetime | None = None


class EdgeResult(BaseModel):
    from_entity: str
    to_entity: str
    relation: str
    confidence: float = 0.8


class RunResponse(BaseModel):
    job_id: str
    tool: str
    status: str
    duration_seconds: float
    findings: list[Finding] = Field(default_factory=list)
    edges: list[EdgeResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # Informational notices (caps hit, false-positives filtered, …).
    # Separate from `errors` so they never mark a run as failed/partial.
    notes: list[str] = Field(default_factory=list)


def make_run_response(
    job_id: str,
    tool: str,
    start: float,
    findings: list["Finding"],
    edges: list["EdgeResult"],
    errors: list[str],
) -> "RunResponse":
    """Build the run response, partitioning informational notes out of
    `errors` and deriving status from the *real* errors only.

    status = success (no real errors) | partial (real errors + some
    findings) | error (real errors, nothing found). NOTE_PREFIX messages
    are moved to `notes` and never affect status.
    """
    real_errors: list[str] = []
    notes: list[str] = []
    for msg in errors or []:
        if msg.startswith(NOTE_PREFIX):
            notes.append(msg[len(NOTE_PREFIX):])
        else:
            real_errors.append(msg)
    status = "success" if not real_errors else ("partial" if findings else "error")
    return RunResponse(
        job_id=job_id,
        tool=tool,
        status=status,
        duration_seconds=round(time.time() - start, 2),
        findings=findings,
        edges=edges,
        errors=real_errors,
        notes=notes,
    )


# --- Manifest --------------------------------------------------------

# --- Admiralty source reliability (NATO / police intelligence practice) ---
#
# A single float confidence per finding was never comparable across tools:
# 0.8 from Sherlock is an HTTP 200 on a profile page, 0.8 from LeakCheck is a
# hit in a verified breach. Those are different KINDS of statement, and no
# amount of tuning the number fixes that.
#
# The Admiralty scale separates the two questions an analyst actually asks:
#
#   Source reliability (A–F)   — how much do we trust this SOURCE, always.
#                                Declared once per tool, here in the manifest.
#   Information credibility (1–6) — how well is THIS finding supported.
#                                Derived per finding by the framework from
#                                corroboration + the tool's own confidence
#                                (see backend/app/services/graph_builder.py).
#
# Together they render as e.g. `B2` — "usually reliable source, probably
# true information" — which is what goes in a case file instead of `0.8`.
#
#   A  completely reliable   — authoritative registry, first-party record
#   B  usually reliable      — established service with its own validation
#   C  fairly reliable       — aggregators, scrapers with a verification gate
#   D  not usually reliable  — open scraping, search engines, forum content
#   E  unreliable            — heuristic or AI estimates
#   F  cannot be judged      — default; used when nothing was declared
#
# Be honest here. Overstating a source is worse than declaring F: an
# investigator can work with "cannot be judged", but not with a wrong claim.
RELIABILITY_LEVELS = ("A", "B", "C", "D", "E", "F")


class ToolDescriptor(BaseModel):
    """One callable tool inside a module."""
    tool: str
    label_key: str
    query_types: list[str]
    default_query_type: str
    requires_key: bool = False
    description_key: Optional[str] = None
    # Admiralty source reliability for THIS tool. See RELIABILITY_LEVELS.
    # Defaults to "F" (cannot be judged) so a tool that never declared one
    # is reported as unrated rather than silently assumed to be good.
    reliability: str = "F"
    # Rough cost of ONE run, declared by the module because only the module
    # author knows what the tool actually does:
    #   "fast"   — a single request or a cached lookup (crtsh, whois, dns)
    #   "medium" — a handful of requests (subfinder, theharvester, holehe)
    #   "slow"   — a sweep over many probes (sherlock, handle_sweep: ~600)
    #
    # The orchestrator uses it for the per-tool timeout and for the order the
    # plan is built in; the UI can warn before an investigator starts a
    # two-minute tool. Default "medium" keeps every existing module valid AND
    # keeps its previous 300 s timeout, so nothing changes until a class is
    # declared. Same rule as `reliability`'s "F": a class is declared only
    # where it was MEASURED, never guessed — an unmeasured tool stays medium.
    latency_class: str = "medium"


class ManifestResponse(BaseModel):
    """A module's self-description, served at GET /manifest."""
    name: str
    label_key: str
    category: str
    version: str = "1.0.0"
    description_key: Optional[str] = None
    tools: list[ToolDescriptor]
