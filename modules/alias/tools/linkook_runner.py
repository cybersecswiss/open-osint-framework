"""
Linkook (JackJuly/linkook) — connected-account discovery for a username.

Goes beyond a flat namecheck (sherlock/whatsmyname/user_scanner): from each
discovered profile it recursively follows *links between profiles* — surfacing
accounts registered under DIFFERENT usernames — and extracts associated email
addresses. (linkook's --check-breach is deliberately NOT used: it also queries a leaked-password collection.)

Runs as a subprocess with Linkook's `--neo4j` JSON export (nodes:
User/SocialMediaAccount/Email, relationships: HAS_ACCOUNT/CONNECTED_TO/…),
which we translate into our graph:
  * SocialMediaAccount → social_account "<platform>/<username>"  (dedups with
    sherlock/holehe/user_scanner; edge username → is_account_of)
  * CONNECTED_TO between two accounts → social_account ↔ social_account
    "linked_account" edge (the recursive-linking value)
  * Email → email_address node (edge username → has_email); becomes a
    pivotable node so the investigator can chain username → email → breach.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile

from schemas import EdgeResult, Finding, NOTE_PREFIX
from verifier import verify_accounts

log = logging.getLogger("module-alias.linkook")

TIMEOUT = 220
MAX_NODES = 300
EXPORT_FILE = "neo4j_export.json"


async def run_linkook(
    query: str, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    username = (query or "").strip().lstrip("@")
    if not username:
        return [], [], ["linkook: empty username"]

    root = f"username:{username.lower()}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    workdir = tempfile.mkdtemp(prefix="linkook_")
    # Linkook writes neo4j_export.json into the current working directory.
    cmd = ["linkook", username, "--neo4j", "--no-color", "-s"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=workdir,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            errors.append(f"{NOTE_PREFIX}linkook timed out after {TIMEOUT}s.")

        path = os.path.join(workdir, EXPORT_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            data = {}

        nodes = (data.get("nodes") or [])[:MAX_NODES]
        rels = data.get("relationships") or []

        # Map linkook node-id → our canonical graph key (entity_type:label),
        # so we can translate CONNECTED_TO relationships into real edges.
        keyof: dict[str, str] = {}
        for n in nodes:
            if not isinstance(n, dict):
                continue
            labels = n.get("labels") or []
            props = n.get("properties") or {}
            nid = n.get("id")
            if "SocialMediaAccount" in labels:
                platform = str(props.get("platform") or "").strip()
                user = str(props.get("username") or username).strip()
                if not platform:
                    continue
                label = f"{platform}/{user}"
                keyof[nid] = f"social_account:{label}"
                findings.append(Finding(
                    entity_type="social_account", platform=platform,
                    label=label, url=props.get("profile_url") or None,
                    confidence=0.65,
                    data={"platform": platform, "username": user,
                          "url": props.get("profile_url") or "",
                          "source": "linkook"},
                ))
                edges.append(EdgeResult(from_entity=root, to_entity=f"social_account:{label}",
                                        relation="is_account_of", confidence=0.65))
            elif "Email" in labels:
                addr = str(props.get("address") or "").strip().lower()
                if not addr:
                    continue
                keyof[nid] = f"email_address:{addr}"
                breached = bool(props.get("is_breached"))
                findings.append(Finding(
                    entity_type="email_address", platform="linkook",
                    label=addr, url=None, confidence=0.6,
                    data={"is_breached": breached, "username": username,
                          "source": "linkook"},
                ))
                edges.append(EdgeResult(from_entity=root, to_entity=f"email_address:{addr}",
                                        relation="has_email", confidence=0.6))

        # CONNECTED_TO (and HAS_EMAIL-style) links between two discovered nodes
        # → real graph edges, keeping only endpoints we actually emitted.
        for r in rels:
            if not isinstance(r, dict):
                continue
            a = keyof.get(r.get("startNode"))
            b = keyof.get(r.get("endNode"))
            if not a or not b or a == b:
                continue
            rtype = str(r.get("type") or "linked").lower()
            if rtype == "has_account":
                continue  # already covered by our root→account edges
            relation = "linked_account" if rtype == "connected_to" else rtype
            edges.append(EdgeResult(from_entity=a, to_entity=b,
                                    relation=relation, confidence=0.55))

        if not findings and not errors:
            errors.append(f"No connected accounts found for '{username}'")
    finally:
        try:
            for fn in os.listdir(workdir):
                os.unlink(os.path.join(workdir, fn))
            os.rmdir(workdir)
        except OSError:
            pass

    # Same two-gate existence check as the other alias tools. linkook's value
    # is the CONNECTIONS between accounts, so a fabricated endpoint does more
    # damage here than elsewhere — it invents a link, not just a node.
    # The e-mail findings have no profile URL and pass through untouched.
    findings, edges, note = await verify_accounts(findings, edges, username, "linkook")
    if note:
        errors.append(note)

    return findings, edges, errors
