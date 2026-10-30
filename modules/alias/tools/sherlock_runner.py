"""
Sherlock wrapper.

Sherlock checks ~400 sites for an account with a given username and
prints `[+] Site: URL` on hits. We invoke the CLI via subprocess
(sherlock-project ships a `sherlock` binary).
"""
from __future__ import annotations

import asyncio

from schemas import EdgeResult, Finding, NOTE_PREFIX
from verifier import verify_findings


async def run_sherlock(
    username: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        proc = await asyncio.create_subprocess_exec(
            "sherlock", username,
            "--print-found", "--no-color", "--timeout", "10",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=240)
        for raw in stdout.decode(errors="replace").splitlines():
            line = raw.strip()
            if not line.startswith("[+]"):
                continue
            # "[+] Twitter: https://twitter.com/<user>"
            parts = line.replace("[+]", "").strip().split(":", 1)
            if len(parts) != 2:
                continue
            platform = parts[0].strip().lower()
            url = parts[1].strip()
            findings.append(Finding(
                entity_type="social_account",
                platform=platform,
                label=f"{platform}/{username}",
                url=url,
                confidence=0.80,
                data={"username": username, "platform": platform, "url": url},
            ))
            edges.append(EdgeResult(
                from_entity=f"username:{username}",
                # Must equal the finding's graph key (entity_type:label);
                # the label uses "platform/username" (slash), so the edge
                # target must too — a "platform:username" (colon) mismatch
                # spawns an empty virtual shadow node with no url.
                to_entity=f"social_account:{platform}/{username}",
                relation="is_account_of",
                confidence=0.80,
            ))
    except asyncio.TimeoutError:
        errors.append("sherlock timeout (240s)")
    except FileNotFoundError:
        errors.append("sherlock binary not found")
    except Exception as e:  # noqa: BLE001
        errors.append(f"sherlock error: {e}")

    # Sherlock has a high false-positive rate (sites that 200 on
    # /<username> for any value, or have generic catch-all pages).
    # Re-check each URL with a content probe and drop the unverified
    # ones — see modules/alias/tools/verifier.py.
    raw_count = len(findings)
    findings = await verify_findings(findings, username)
    dropped = raw_count - len(findings)
    if dropped > 0:
        # NOTE_PREFIX: a working false-positive filter is information, not a
        # failure. Without it make_run_response counts this as a real error and
        # marks the whole search "partial" — which is why nearly every username
        # search reported partial while doing exactly what it should.
        errors.append(f"{NOTE_PREFIX}sherlock: {dropped} false positives filtered "
                      f"({len(findings)}/{raw_count} verified)")
    # Edges that pointed at dropped findings are now orphans — keep
    # only edges whose target survived.
    valid_targets = {f"social_account:{f.label}" for f in findings}
    edges = [e for e in edges if e.to_entity in valid_targets]

    return findings, edges, errors
