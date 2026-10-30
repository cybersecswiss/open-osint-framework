"""
User Scanner (kaifcodec/user-scanner) — 2-in-1 username + email presence.

A keyless, pip-installed OSINT CLI that checks a username across 190+ social/
developer/creator/community/gaming platforms AND an email across 120+ sites
(registration check). Complements sherlock/whatsmyname (broader gaming/creator
coverage) and holehe (a second independent email-registration source).

Runs as a subprocess with JSON output (same pattern as sherlock/holehe/
theharvester). Node/edge conventions are matched to sherlock (username) and
holehe (email) so results dedup instead of spawning shadow nodes:
  * username  →  social_account "<site>/<username>"  (username → is_account_of)
  * email     →  social_account "<site>/<email>"     (email → registered_on)

Safety: `--allow-loud` (sites that send password-reset/notification emails to
the target) is deliberately NOT passed — we never tip off a subject.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile

from schemas import EdgeResult, Finding, NOTE_PREFIX
from verifier import verify_accounts

log = logging.getLogger("module-alias.user_scanner")

TIMEOUT = 220          # subprocess wall-clock cap (full scan of ~190/120 sites)
MAX_RESULTS = 200


async def run_user_scanner(
    query: str, query_type: str = "username", job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    is_email = query_type == "email"
    q = (query or "").strip()
    if not is_email:
        q = q.lstrip("@")
    if not q:
        return [], [], ["user_scanner: empty query"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    root = f"email:{q}" if is_email else f"username:{q.lower()}"
    # user-scanner's JSON status: username hits report "Found", email hits
    # report "Registered" (the CLI help's "Available/Taken" wording is stale).
    ok_status = "Registered" if is_email else "Found"
    relation = "registered_on" if is_email else "is_account_of"

    tmp = tempfile.NamedTemporaryFile("r", suffix=".json", delete=False)
    tmp.close()
    flag = "-e" if is_email else "-u"
    cmd = ["user-scanner", flag, q, "--only-found", "--no-nsfw",
           "-f", "json", "-o", tmp.name]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            errors.append(f"{NOTE_PREFIX}user_scanner timed out after {TIMEOUT}s "
                          "— partial or no results.")
            stderr = b""

        try:
            with open(tmp.name, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            data = []

        if not isinstance(data, list):
            data = []

        seen: set[str] = set()
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status", "")).strip() != ok_status:
                continue
            site = str(entry.get("site_name") or "").strip()
            if not site:
                continue
            label = f"{site}/{q}"
            if label in seen:
                continue
            seen.add(label)
            # username: the profile URL is a real pivot; email: the site root is
            # misleading (holehe convention) → leave url unset.
            url = (entry.get("url") or None) if not is_email else None
            findings.append(Finding(
                entity_type="social_account", platform=site,
                label=label, url=url, confidence=0.6,
                data={"site": site, "category": entry.get("category") or "",
                      "identifier": q, "status": ok_status,
                      "extra": entry.get("extra") or {},
                      **({"url": url} if url else {}),
                      "source": "user_scanner"},
            ))
            edges.append(EdgeResult(from_entity=root,
                                    to_entity=f"social_account:{label}",
                                    relation=relation, confidence=0.6))
            if len(findings) >= MAX_RESULTS:
                errors.append(f"{NOTE_PREFIX}user_scanner: capped at {MAX_RESULTS} "
                              "hits.")
                break

        if not findings and not errors:
            kind = "email registrations" if is_email else "accounts"
            errors.append(f"No {kind} found for '{q}'")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # user_scanner reports a hit on an HTTP status match alone, which catches
    # every site that serves 200 for any path. Run the same two-gate existence
    # check Sherlock and WhatsMyName use, so its accounts are the same kind of
    # claim as theirs instead of the weakest nodes in the graph.
    # E-mail-mode findings carry no profile URL and are left untouched.
    findings, edges, note = await verify_accounts(findings, edges, q, "user_scanner")
    if note:
        errors.append(note)

    return findings, edges, errors
