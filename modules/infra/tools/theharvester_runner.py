"""
theHarvester wrapper.

theHarvester mines search engines / passive DNS / cert-transparency
sources for a domain and returns the e-mails, sub-domains (hosts) and
IPs it can attribute to that domain.

Install note: theHarvester pins its own fastapi/uvicorn/playwright and
would clash with this module's app dependencies, so the Dockerfile
installs it into an ISOLATED virtualenv and exposes only its CLI on
PATH (`theHarvester`). We invoke that CLI as a subprocess, exactly like
subfinder, and parse the JSON report it writes with `-f`.

Only keyless sources are queried (see SOURCES); key-gated sources are
skipped by theHarvester itself when no API key is configured.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile

from schemas import EdgeResult, Finding

# Keyless passive sources valid in theHarvester 4.11.x. theHarvester
# ABORTS the whole run if any name here is unknown to the installed
# version, so only list sources confirmed present. Key-gated sources are
# skipped gracefully when no key is configured, so they'd be harmless —
# we simply omit them to keep runs fast and keyless.
SOURCES = "crtsh,hackertarget,rapiddns,otx,duckduckgo,certspotter,urlscan,subdomaincenter,commoncrawl"

# A host is kept only if it is a real sub-domain of the queried domain
# and a syntactically valid hostname (drops wildcards like *.x.com and
# cross-domain noise theHarvester sometimes emits).
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62})(\.[a-z0-9]([a-z0-9-]{0,62}))*$")

# Caps so a big domain can't flood the graph / agent ingest in one run.
MAX_EMAILS = 200
MAX_HOSTS = 200
MAX_IPS = 100

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _clean_domain(raw: str) -> str:
    d = raw.strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)      # strip scheme
    d = d.split("/", 1)[0]                # strip path
    return d.strip(".")


async def run_theharvester(
    domain: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    domain = _clean_domain(domain)
    if not domain:
        return [], [], ["theHarvester: empty domain"]

    safe_job = re.sub(r"[^A-Za-z0-9_-]", "_", job_id or "job")
    base = os.path.join(tempfile.gettempdir(), f"th_{safe_job}")
    json_path = base + ".json"
    xml_path = base + ".xml"

    try:
        proc = await asyncio.create_subprocess_exec(
            "theHarvester", "-d", domain, "-b", SOURCES, "-f", base,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=240)

        # theHarvester often exits non-zero when a single source fails,
        # yet still writes a valid JSON report. Gate on the file, not the
        # return code.
        if not os.path.exists(json_path):
            hint = stderr.decode(errors="replace").strip().splitlines()
            tail = hint[-1] if hint else "no output"
            errors.append(f"theHarvester produced no report ({tail})")
            return findings, edges, errors

        with open(json_path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh) or {}

        emails = data.get("emails") or []
        hosts = data.get("hosts") or []
        ips = list(data.get("ips") or [])

        # ---- e-mails ----
        seen_emails: set[str] = set()
        for raw in emails:
            email = str(raw).strip().lower()
            if not _EMAIL_RE.match(email) or email in seen_emails:
                continue
            seen_emails.add(email)
            if len(seen_emails) > MAX_EMAILS:
                break
            findings.append(Finding(
                entity_type="email",
                label=email,
                confidence=0.75,
                data={"parent_domain": domain, "source": "theharvester"},
            ))
            edges.append(EdgeResult(
                from_entity=f"domain:{domain}",
                to_entity=f"email:{email}",
                relation="has_email",
                confidence=0.8,
            ))

        # ---- hosts (sub-domains, sometimes "host:ip") ----
        seen_hosts: set[str] = set()
        for raw in hosts:
            entry = str(raw).strip().lower()
            if not entry:
                continue
            host, _, ip_part = entry.partition(":")
            host = host.strip().strip(".")
            ip_part = ip_part.strip()
            # harvest a co-located IPv4 regardless of host validity
            if _IP_RE.match(ip_part):
                ips.append(ip_part)
            # quality gate: real sub-domain of the target, valid hostname
            is_sub = host == domain or host.endswith("." + domain)
            if (not host or host in seen_hosts or host.startswith("*")
                    or not is_sub or not _HOST_RE.match(host)):
                continue
            seen_hosts.add(host)
            if len(seen_hosts) <= MAX_HOSTS:
                findings.append(Finding(
                    entity_type="domain",
                    label=host,
                    url=f"https://{host}",
                    confidence=0.8,
                    data={"parent_domain": domain, "source": "theharvester"},
                ))
                edges.append(EdgeResult(
                    from_entity=f"domain:{domain}",
                    to_entity=f"domain:{host}",
                    relation="has_subdomain",
                    confidence=0.85,
                ))

        # ---- IPs ----
        seen_ips: set[str] = set()
        for raw in ips:
            ip = str(raw).strip()
            if not _IP_RE.match(ip) or ip in seen_ips:
                continue
            seen_ips.add(ip)
            if len(seen_ips) > MAX_IPS:
                break
            findings.append(Finding(
                entity_type="ip",
                label=ip,
                confidence=0.7,
                data={"parent_domain": domain, "source": "theharvester"},
            ))
            edges.append(EdgeResult(
                from_entity=f"domain:{domain}",
                to_entity=f"ip:{ip}",
                relation="resolves_to",
                confidence=0.75,
            ))

        if not findings:
            errors.append("theHarvester: no emails/hosts/ips found for this domain")

    except asyncio.TimeoutError:
        errors.append("theHarvester timeout (240s)")
    except FileNotFoundError:
        errors.append("theHarvester not installed")
    except json.JSONDecodeError as e:
        errors.append(f"theHarvester: unreadable JSON report: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"theHarvester error: {e}")
    finally:
        for p in (json_path, xml_path):
            try:
                os.remove(p)
            except OSError:
                pass

    return findings, edges, errors
