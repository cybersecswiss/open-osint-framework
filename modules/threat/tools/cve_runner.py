"""CVE context from NVD, with CISA KEV as the "is it actually used" flag.

Shodan tells you a host runs a vulnerable service. On its own that is a
property of the software, not a lead. What makes it a lead is whether the
vulnerability is *known to be exploited in the wild* — CISA's Known Exploited
Vulnerabilities catalogue — and whether it has been used in ransomware
campaigns, which KEV also records.

Both sources are open:

    NVD   https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=…
    KEV   https://www.cisa.gov/…/known_exploited_vulnerabilities.csv

NVD rate-limits anonymous callers hard (roughly 5 requests per 30 s), which
is fine for a per-CVE lookup and is why this runner never enumerates.

The KEV catalogue is ~900 KB and changes daily, so it is cached in-process
for a day. On a cache miss the CVE is still returned with its NVD data and a
note saying the KEV status could not be checked — a missing flag must not be
reported as "not exploited".
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

NVD = "https://services.nvd.nist.gov/rest/json/cves/2.0"
KEV_CSV = ("https://www.cisa.gov/sites/default/files/csv/"
           "known_exploited_vulnerabilities.csv")
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 45
KEV_TTL = 24 * 3600

CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,7}$", re.IGNORECASE)

# cve id (upper) -> KEV row. Populated lazily, refreshed daily.
_kev_cache: dict[str, dict[str, str]] = {}
_kev_fetched_at: float = 0.0

log = logging.getLogger("module-threat.cve")


async def _kev_index(client: httpx.AsyncClient) -> dict[str, dict[str, str]] | None:
    global _kev_fetched_at
    if _kev_cache and (time.time() - _kev_fetched_at) < KEV_TTL:
        return _kev_cache
    try:
        r = await client.get(KEV_CSV)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("KEV catalogue unavailable: %s", e)
        # Serve a stale copy rather than nothing — an outdated KEV flag is
        # still far more useful than none, and its age is reported.
        return _kev_cache or None
    rows = csv.DictReader(io.StringIO(r.text))
    fresh = {(row.get("cveID") or "").upper(): row for row in rows if row.get("cveID")}
    if fresh:
        _kev_cache.clear()
        _kev_cache.update(fresh)
        _kev_fetched_at = time.time()
    return _kev_cache or None


def _as_dt(value):
    """ISO string from the source -> datetime, or None when unparseable.

    None is the honest answer: a made-up date on an evidentiary field is
    worse than an empty one."""
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _cvss(cve: dict[str, Any]) -> dict[str, Any]:
    """Highest-version CVSS available. v3.1 → v3.0 → v2."""
    metrics = cve.get("metrics") or {}
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if entries:
            data = entries[0].get("cvssData") or {}
            return {
                "score": data.get("baseScore"),
                "severity": data.get("baseSeverity") or entries[0].get("baseSeverity"),
                "vector": data.get("vectorString"),
                "version": data.get("version"),
            }
    return {}


async def run_cve(
    query: str, query_type: str, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    cve_id = (query or "").strip().upper()
    if not CVE_RE.match(cve_id):
        return [], [], [f"cve_lookup: '{query}' is not a CVE id (expected CVE-YYYY-NNNN)"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers,
                                 follow_redirects=True) as client:
        try:
            r = await client.get(NVD, params={"cveId": cve_id})
        except httpx.TimeoutException:
            return findings, edges, [f"cve_lookup: NVD timeout ({TIMEOUT}s)"]
        except httpx.HTTPError as e:
            return findings, edges, [f"cve_lookup: NVD unreachable: {e}"]

        if r.status_code == 403 or r.status_code == 429:
            return findings, edges, ["cve_lookup: NVD rate-limited the request "
                                     "(anonymous callers get ~5 per 30 s) — retry shortly"]
        if r.status_code == 404:
            return findings, edges, [f"cve_lookup: NVD does not know {cve_id}"]
        if r.status_code != 200:
            return findings, edges, [f"cve_lookup: NVD HTTP {r.status_code}"]

        try:
            vulns = (r.json() or {}).get("vulnerabilities") or []
        except ValueError:
            return findings, edges, ["cve_lookup: NVD returned non-JSON"]
        if not vulns:
            return findings, edges, [f"cve_lookup: no NVD record for {cve_id}"]

        cve = vulns[0].get("cve") or {}
        kev = await _kev_index(client)

    descriptions = [d.get("value") for d in (cve.get("descriptions") or [])
                    if d.get("lang") == "en"]
    cvss = _cvss(cve)
    weaknesses = [
        d.get("value")
        for w in (cve.get("weaknesses") or [])
        for d in (w.get("description") or [])
        if d.get("value", "").startswith("CWE-")
    ]

    kev_row = (kev or {}).get(cve_id)
    if kev is None:
        errors.append(f"{NOTE_PREFIX}cve_lookup: the CISA KEV catalogue could not be "
                      "fetched, so exploited-in-the-wild status is UNKNOWN for "
                      f"{cve_id} — not 'no'.")

    data: dict[str, Any] = {
        "description": (descriptions[0] if descriptions else "")[:1200],
        "published": cve.get("published"),
        "last_modified": cve.get("lastModified"),
        "cvss_score": cvss.get("score"),
        "cvss_severity": cvss.get("severity"),
        "cvss_vector": cvss.get("vector"),
        "cwe": weaknesses[:5],
        "reference_count": len(cve.get("references") or []),
        "source": "nvd",
    }
    if kev_row:
        data.update({
            "kev_listed": True,
            "kev_date_added": kev_row.get("dateAdded"),
            "kev_due_date": kev_row.get("dueDate"),
            "kev_required_action": kev_row.get("requiredAction"),
            "known_ransomware_use": (kev_row.get("knownRansomwareCampaignUse") or "").lower(),
            "vendor": kev_row.get("vendorProject"),
            "product": kev_row.get("product"),
        })
    elif kev is not None:
        data["kev_listed"] = False

    # A KEV entry is a statement by a national authority that this is being
    # exploited right now. That earns the highest confidence the runner emits.
    confidence = 0.95 if kev_row else 0.85

    findings.append(Finding(
        entity_type="vulnerability", label=cve_id,
        url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        confidence=confidence, platform="nvd", data=data,
        # NVD publication date — when the vulnerability became public, not
        # when we asked about it.
        found_at=_as_dt(cve.get("published")),
    ))

    if kev_row:
        findings.append(Finding(
            entity_type="vulnerability", label=f"KEV:{cve_id}",
            url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            confidence=0.95, platform="cisa-kev",
            data={"cve": cve_id,
                  "vendor": kev_row.get("vendorProject"),
                  "product": kev_row.get("product"),
                  "date_added": kev_row.get("dateAdded"),
                  "ransomware_use": kev_row.get("knownRansomwareCampaignUse"),
                  "source": "cisa-kev"},
        ))
        edges.append(EdgeResult(
            from_entity=f"vulnerability:{cve_id}",
            to_entity=f"vulnerability:KEV:{cve_id}",
            relation="known_exploited", confidence=0.95,
        ))
        if (kev_row.get("knownRansomwareCampaignUse") or "").lower() == "known":
            errors.append(f"{NOTE_PREFIX}cve_lookup: {cve_id} is listed in CISA KEV "
                          "AND is known to be used in ransomware campaigns.")
        else:
            errors.append(f"{NOTE_PREFIX}cve_lookup: {cve_id} is listed in CISA KEV "
                          "(exploited in the wild).")

    return findings, edges, errors
