"""FBI-Watchdog — detect law-enforcement SEIZURES and infrastructure changes
of a cybercrime domain or hidden service.

Two honest signals, no fabrication:

1. **Seizure banner** — fetch the site (``.onion`` over the bundled Tor
   SOCKS proxy, clearnet direct) and scan the rendered text/title for the
   real language takedown splash pages use ("this domain has been seized",
   "seized by", agency names, "Operation …"). An explicit seizure phrase is
   a STRONG signal (0.85); an agency/operation mention alone is a lead
   (0.55). Emits a ``seizure_notice`` node naming the agencies found.

2. **Infra snapshot** — current A records, nameservers, HTTP status, redirect
   target and ``Server`` header, attached to the target node. This is what a
   monitoring re-run diffs to catch an infrastructure CHANGE (nameservers
   flipping to a takedown host, a fresh redirect) even before a banner
   appears. Point-in-time here; the monitoring subsystem does the diffing.

Nothing auto-chains. The tool reports what it observed and how strongly;
the investigator decides what it means for their case.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX

log = logging.getLogger("module-darknet.seizure")

TOR_PROXY = os.getenv("TOR_SOCKS_PROXY", "").strip()
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0")
TIMEOUT = 12.0    # per attempt; a dead domain costs at most 2× (https→http)
MAX_TEXT = 20000  # chars of body text we scan

# Explicit takedown language — an exact match is a strong seizure signal.
SEIZURE_PHRASES = [
    "has been seized", "have been seized", "this domain has been seized",
    "this hidden service has been seized", "this site has been seized",
    "this website has been seized", "domain seizure", "seized as part of",
    "seized pursuant to", "was seized", "been seized by", "seized by",
    "beschlagnahmt", "saisi dans le cadre", "incautado",
]
# Agencies / operations — corroborating context, weaker on their own.
AGENCIES = [
    "Federal Bureau of Investigation", "FBI", "Europol", "Eurojust",
    "Bundeskriminalamt", "BKA", "National Crime Agency", "NCA",
    "Department of Justice", "U.S. Attorney", "Homeland Security Investigations",
    "Secret Service", "Guardia Civil", "Politie", "Interpol", "IRS-CI",
    "Australian Federal Police", "AFP", "Gendarmerie", "ZIT",
    "Drug Enforcement Administration", "DEA", " Transnational",
]
OPERATION_RE = re.compile(r"operation\s+[A-Z][\w-]+", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _is_onion(host: str) -> bool:
    return host.lower().rstrip("/").endswith(".onion")


def _clean_host(query: str) -> str:
    h = (query or "").strip()
    h = re.sub(r"^https?://", "", h, flags=re.I).strip("/")
    return h.split("/")[0].lower()


async def _dns_snapshot(host: str) -> dict:
    """Clearnet A + NS records — the infra fingerprint a re-run diffs."""
    out: dict = {}
    try:
        import dns.asyncresolver
        r = dns.asyncresolver.Resolver()
        r.lifetime = 6.0
        for rtype in ("A", "NS"):
            try:
                ans = await r.resolve(host, rtype)
                out[rtype.lower()] = sorted(str(x).rstrip(".") for x in ans)
            except Exception:  # noqa: BLE001 — NXDOMAIN/timeout → absent
                pass
    except Exception:  # noqa: BLE001
        pass
    return out


def _scan(text: str) -> tuple[list[str], list[str], list[str]]:
    """Return (matched seizure phrases, agencies, operations) found in text."""
    low = text.lower()
    phrases = [p for p in SEIZURE_PHRASES if p in low]
    agencies = sorted({a for a in AGENCIES if re.search(rf"\b{re.escape(a)}\b", text)})
    ops = sorted({m.group(0) for m in OPERATION_RE.finditer(text)})
    return phrases, agencies, ops


async def run_seizure_watch(
    query: str, query_type: str = "domain", job_id: str = "adhoc"
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    host = _clean_host(query)
    if not host or "." not in host:
        return [], [], ["seizure_watch: provide a domain or .onion host."]

    onion = _is_onion(host)
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    # Node identity: onion → onion_service, clearnet → domain
    target_type = "onion_service" if onion else "domain"
    target_key = f"{target_type}:{host}"

    # --- infra snapshot (clearnet DNS; onions have no DNS) ---
    snapshot: dict = {"host": host, "checked_over": "tor" if onion else "clearnet"}
    if not onion:
        snapshot.update(await _dns_snapshot(host))

    # --- fetch the page ---
    proxy = TOR_PROXY if onion else None
    if onion and not proxy:
        errors.append(f"{NOTE_PREFIX}No Tor path configured — cannot reach the "
                      f"hidden service to check for a seizure banner.")
    else:
        scheme = "http" if onion else "https"
        url = f"{scheme}://{host}/"
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, follow_redirects=True, proxy=proxy,
                headers={"User-Agent": USER_AGENT}, verify=not onion,
            ) as c:
                r = await c.get(url)
                snapshot["http_status"] = r.status_code
                snapshot["server"] = r.headers.get("server")
                if str(r.url).rstrip("/") != url.rstrip("/"):
                    snapshot["redirected_to"] = str(r.url)
                body = r.text[:MAX_TEXT]
        except httpx.HTTPError as e:
            # clearnet https can fail → retry http once
            body = ""
            if not onion:
                try:
                    async with httpx.AsyncClient(
                        timeout=TIMEOUT, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT}) as c:
                        r = await c.get(f"http://{host}/")
                        snapshot["http_status"] = r.status_code
                        snapshot["server"] = r.headers.get("server")
                        body = r.text[:MAX_TEXT]
                except httpx.HTTPError as e2:
                    errors.append(f"{NOTE_PREFIX}Site unreachable ({type(e2).__name__}); "
                                  f"reporting DNS snapshot only.")
            else:
                errors.append(f"{NOTE_PREFIX}Hidden service unreachable over Tor "
                              f"({type(e).__name__}) — may already be offline/seized.")

        if body:
            tm = TITLE_RE.search(body)
            if tm:
                snapshot["title"] = TAG_RE.sub("", tm.group(1)).strip()[:200]
            plain = TAG_RE.sub(" ", body)
            phrases, agencies, ops = _scan(plain)

            if phrases or (agencies and ops):
                strong = bool(phrases)
                conf = 0.85 if strong else 0.55
                who = agencies or ["law enforcement"]
                label = "SEIZED — " + ", ".join(who[:3])
                findings.append(Finding(
                    entity_type="seizure_notice", platform="fbi_watchdog",
                    label=label, url=url, confidence=conf,
                    data={"host": host, "agencies": agencies, "operations": ops,
                          "matched_phrases": phrases,
                          "verdict": "seizure_confirmed" if strong else "possible_seizure",
                          "title": snapshot.get("title"), "source": "fbi_watchdog"},
                ))
                edges.append(EdgeResult(from_entity=target_key,
                                        to_entity=f"seizure_notice:{label}",
                                        relation="seized", confidence=conf))
                snapshot["seizure"] = "confirmed" if strong else "possible"
            elif agencies:
                snapshot["seizure"] = f"agency mention only: {', '.join(agencies[:3])}"
            else:
                snapshot["seizure"] = "no indicators"

    # target node always emitted, carrying the infra snapshot for diffing
    findings.insert(0, Finding(
        entity_type=target_type, platform="fbi_watchdog", label=host,
        url=(f"http://{host}/" if onion else f"https://{host}/"),
        confidence=0.6, data={**snapshot, "source": "fbi_watchdog"},
    ))

    if snapshot.get("seizure") in (None, "no indicators"):
        errors.append(f"{NOTE_PREFIX}No seizure banner detected on {host}. Infra "
                      f"snapshot recorded — re-run via Monitoring to catch changes.")
    return findings, edges, errors
