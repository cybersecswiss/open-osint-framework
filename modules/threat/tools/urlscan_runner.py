"""
urlscan.io lookup (keyless public search).

urlscan's public search API (``/api/v1/search/``) is keyless and returns
what urlscan already knows about a domain / IP / URL: the pages scanned,
their resolved IP + ASN + country + server, a verdict, and a screenshot.
Great for phishing / C2 triage and a strong pivot target (domain → the
IPs it resolved to, an IP → the domains seen on it).

Submitting a *new* live scan needs a free API key; that can be added
later. This runner only reads existing scan data, so it needs no key.
"""
from __future__ import annotations

import urllib.parse

import httpx

from schemas import EdgeResult, Finding

SEARCH_URL = "https://urlscan.io/api/v1/search/"
USER_AGENT = "OOF/1.0"
MAX_RESULTS = 15
MAX_NODES = 15


def _query_expr(value: str, query_type: str) -> str:
    if query_type == "ip":
        return f"page.ip:{value}"
    if query_type == "url":
        return f'page.url:"{value}"'
    # domain (default)
    return f"domain:{value}"


async def run_urlscan(
    query: str, query_type: str, options: dict | None = None,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    q = (query or "").strip()
    if not q:
        return [], [], ["urlscan: empty query"]

    params = {"q": _query_expr(q, query_type), "size": str(MAX_RESULTS)}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(SEARCH_URL, params=params)
            if r.status_code == 429:
                return [], [], ["urlscan: rate-limited (HTTP 429), try again shortly"]
            if r.status_code != 200:
                return [], [], [f"urlscan HTTP {r.status_code}"]
            body = r.json()
    except httpx.TimeoutException:
        return [], [], ["urlscan timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"urlscan error: {e}"]

    results = body.get("results") or []
    if not results:
        return [], [], []

    root = f"{query_type}:{q}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    # Summary node for the latest scan (report link + screenshot + verdict).
    latest = results[0]
    rid = latest.get("_id")
    report_url = (f"https://urlscan.io/result/{rid}/" if rid
                  else f"https://urlscan.io/search/#{urllib.parse.quote(q)}")
    page = latest.get("page", {})
    findings.append(Finding(
        entity_type="urlscan_report", platform="urlscan",
        label=f"urlscan:{q}", url=report_url, confidence=0.6,
        data={"query": q, "total_scans": body.get("total"),
              "latest_url": latest.get("task", {}).get("url"),
              "screenshot": latest.get("screenshot"),
              "verdict_score": (latest.get("verdicts") or {}).get("overall", {}).get("score"),
              "server": page.get("server"), "country": page.get("country"),
              "source": "urlscan", "url": report_url},
    ))
    edges.append(EdgeResult(from_entity=root,
                            to_entity=f"urlscan_report:urlscan:{q}",
                            relation="scanned_by", confidence=0.6))

    # Distinct resolved IPs (asn/country as context) and distinct domains
    # seen across the scans — both excellent pivot nodes. Skip whatever
    # equals the query itself to avoid a self-loop.
    ips: dict[str, dict] = {}
    domains: dict[str, dict] = {}
    for res in results:
        p = res.get("page", {})
        ip = p.get("ip")
        dom = (p.get("domain") or "").lower()
        if ip and ip != q and ip not in ips:
            ips[ip] = {"asn": p.get("asn"), "asnname": p.get("asnname"),
                       "country": p.get("country"), "server": p.get("server"),
                       "source": "urlscan"}
        if dom and dom != q.lower() and dom not in domains:
            domains[dom] = {"asn": p.get("asn"), "country": p.get("country"),
                            "source": "urlscan"}

    for ip, data in list(ips.items())[:MAX_NODES]:
        findings.append(Finding(entity_type="ip", platform="urlscan",
                                label=ip, confidence=0.55, data={**data, "ip": ip}))
        edges.append(EdgeResult(from_entity=root, to_entity=f"ip:{ip}",
                                relation="resolved_ip", confidence=0.55))
    for dom, data in list(domains.items())[:MAX_NODES]:
        findings.append(Finding(entity_type="domain", platform="urlscan",
                                label=dom, confidence=0.5,
                                data={**data, "domain": dom,
                                      "url": f"https://{dom}"}))
        edges.append(EdgeResult(from_entity=root, to_entity=f"domain:{dom}",
                                relation="related_domain", confidence=0.5))

    return findings, edges, []
