"""
Holehe wrapper.

Holehe checks which of ~120 sites have an account registered to a
given email address. We invoke the CLI in a subprocess and parse the
"[+]" lines from its plain-text output.
"""
from __future__ import annotations

import asyncio
import logging

from schemas import EdgeResult, Finding

log = logging.getLogger("module-leaks.holehe")


async def run_holehe(
    email: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        proc = await asyncio.create_subprocess_exec(
            "holehe", email, "--only-used", "--no-color",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        for raw in stdout.decode(errors="replace").splitlines():
            line = raw.strip()
            if not line.startswith("[+]"):
                continue
            # Format: "[+] platform.com" — first token after the marker
            tokens = line.replace("[+]", "").strip().split()
            if not tokens:
                continue
            platform = tokens[0].lower().rstrip(":")
            # No per-account deep-link: holehe only confirms an account
            # *exists* on the platform, it doesn't return its URL. Emitting
            # https://<platform> looked like an account link but was just
            # the site root — misleading as a pivot, so leave url unset.
            findings.append(Finding(
                entity_type="social_account",
                platform=platform,
                label=f"{platform}/{email}",
                url=None,
                confidence=0.85,
                data={"registered_email": email, "platform": platform,
                      "note": "account confirmed to exist; no deep-link available"},
            ))
            edges.append(EdgeResult(
                from_entity=f"email:{email}",
                # Must equal the finding's graph key (entity_type:label);
                # label is "platform/email" (slash) — a colon form spawns
                # an empty virtual shadow node.
                to_entity=f"social_account:{platform}/{email}",
                relation="registered_on",
                confidence=0.85,
            ))
    except asyncio.TimeoutError:
        errors.append("holehe timeout (120s)")
    except FileNotFoundError:
        errors.append("holehe binary not found (install failed?)")
    except Exception as e:  # noqa: BLE001
        errors.append(f"holehe error: {e}")

    return findings, edges, errors
