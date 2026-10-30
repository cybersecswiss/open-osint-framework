"""
Shodan host intelligence + favicon-hash infrastructure clustering.

Two key-gated tools (SHODAN_API_KEY — free membership includes a small
monthly query credit; a paid key raises it):

  * shodan_host   — ip | domain → open ports / banners / products / CVEs.
    Emits a `service` node per open port and a `vulnerability` node per
    CVE, linked back to the host so an investigator can pivot from an IP
    to what it exposes.
  * favicon_pivot — url → the site's favicon mmh3 hash (computed the same
    way Shodan indexes it) → every OTHER host on the internet serving the
    SAME favicon. Clusters a phishing kit / C2 panel spread across many
    IPs to one actor via the `same_favicon` edge.

Both degrade cleanly to a "SHODAN_API_KEY not set" error when the key is
missing — the module stays healthy and the rest of the search runs.
"""
from __future__ import annotations

import base64
import logging
from urllib.parse import urlsplit

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

log = logging.getLogger("module-infra.shodan")

API = "https://api.shodan.io"
MAX_SERVICES = 50          # open ports rendered per host
MAX_VULNS_PER_SVC = 25     # CVEs rendered per service
MAX_FAVICON_HOSTS = 100    # clustered hosts rendered per favicon


# --- shodan_host -----------------------------------------------------

async def _resolve_domain(client: httpx.AsyncClient, domain: str, key: str) -> str | None:
    r = await client.get(f"{API}/dns/resolve", params={"hostnames": domain, "key": key})
    if r.status_code != 200:
        return None
    return (r.json() or {}).get(domain)


async def _host_lookup(
    client: httpx.AsyncClient, ip: str, key: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    r = await client.get(f"{API}/shodan/host/{ip}", params={"key": key})
    if r.status_code == 401:
        return [], [], ["Shodan: SHODAN_API_KEY refused (401)."]
    if r.status_code == 404:
        return [], [], [f"{NOTE_PREFIX}Shodan has no host data for {ip}."]
    if r.status_code != 200:
        return [], [], [f"Shodan host lookup HTTP {r.status_code} for {ip}."]

    data = r.json() or {}
    root = f"ip:{ip}"

    org = (data.get("org") or data.get("isp") or "").strip()
    if org:
        edges.append(EdgeResult(from_entity=root,
                                to_entity=f"organization:{org.lower()}",
                                relation="hosted_by", confidence=0.7))
    for hn in (data.get("hostnames") or [])[:10]:
        hn = str(hn).lower().strip(".")
        if hn:
            edges.append(EdgeResult(from_entity=root, to_entity=f"domain:{hn}",
                                    relation="resolves_to", confidence=0.6))

    seen_ports: set[int] = set()
    for svc in (data.get("data") or [])[:MAX_SERVICES]:
        port = svc.get("port")
        if port is None or port in seen_ports:
            continue
        seen_ports.add(port)
        product = (svc.get("product") or "").strip()
        version = (svc.get("version") or "").strip()
        label = f"{ip}:{port}"
        findings.append(Finding(
            entity_type="service", platform="shodan",
            label=label, confidence=0.8,
            data={
                "ip": ip, "port": port,
                "transport": svc.get("transport", "tcp"),
                "product": product, "version": version,
                "cpe": svc.get("cpe") or [],
                "banner": (svc.get("data") or "")[:400],
                "source": "shodan",
            },
        ))
        edges.append(EdgeResult(from_entity=root, to_entity=f"service:{label}",
                                relation="runs_service", confidence=0.85))

        vulns = svc.get("vulns") or {}
        for cve in list(vulns)[:MAX_VULNS_PER_SVC]:
            meta = vulns[cve] if isinstance(vulns[cve], dict) else {}
            findings.append(Finding(
                entity_type="vulnerability", platform="shodan",
                label=cve, url=f"https://nvd.nist.gov/vuln/detail/{cve}",
                confidence=0.6,
                data={"cve": cve, "ip": ip, "port": port,
                      "cvss": meta.get("cvss"),
                      "summary": (meta.get("summary") or "")[:300],
                      "source": "shodan"},
            ))
            edges.append(EdgeResult(from_entity=f"service:{label}",
                                    to_entity=f"vulnerability:{cve}",
                                    relation="has_vulnerability", confidence=0.6))

    if not seen_ports:
        errors.append(f"{NOTE_PREFIX}Shodan knows {ip} but lists no open services.")
    return findings, edges, errors


async def run_shodan_host(
    query: str, query_type: str = "ip", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "SHODAN_API_KEY")
    if not key:
        return [], [], ["Shodan: SHODAN_API_KEY not set — add it in Global-Admin "
                        "→ Settings (free at https://account.shodan.io)."]
    q = (query or "").strip()
    if not q:
        return [], [], ["Shodan: empty query."]

    async with httpx.AsyncClient(timeout=30) as client:
        ip = q
        if query_type == "domain":
            try:
                ip = await _resolve_domain(client, q, key)
            except httpx.TimeoutException:
                return [], [], ["Shodan: DNS resolve timed out."]
            if not ip:
                return [], [], [f"Shodan: could not resolve {q} to an IP."]
        try:
            findings, edges, errors = await _host_lookup(client, ip, key)
        except httpx.TimeoutException:
            return [], [], ["Shodan: host lookup timed out."]

        if query_type == "domain":
            edges.append(EdgeResult(from_entity=f"domain:{q.lower()}",
                                    to_entity=f"ip:{ip}",
                                    relation="resolves_to", confidence=0.8))
        return findings, edges, errors


# --- favicon_pivot ---------------------------------------------------

def _favicon_hash(content: bytes) -> int:
    """Shodan's favicon hash convention: mmh3.hash of the base64-encoded
    icon bytes (base64.encodebytes → the chunked form with newlines, as
    Shodan itself computes it). Returns the signed 32-bit int used in the
    `http.favicon.hash:` dork."""
    import mmh3  # lazy — keeps the healthcheck import light
    return mmh3.hash(base64.encodebytes(content))


async def run_favicon_pivot(
    query: str, query_type: str = "url", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "SHODAN_API_KEY")
    if not key:
        return [], [], ["Favicon pivot: SHODAN_API_KEY not set — add it in "
                        "Global-Admin → Settings (free at https://account.shodan.io)."]
    url = (query or "").strip()
    if not url:
        return [], [], ["Favicon pivot: empty url."]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parts = urlsplit(url)
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        # 1) fetch the favicon (given URL if it already points at an icon,
        #    else the site's /favicon.ico).
        candidates: list[str] = []
        if url.rstrip("/").lower().endswith((".ico", ".png")):
            candidates.append(url)
        candidates.append(f"{parts.scheme}://{parts.netloc}/favicon.ico")
        content: bytes | None = None
        for cand in candidates:
            try:
                r = await client.get(cand)
            except Exception as e:  # noqa: BLE001
                log.info("favicon fetch failed %s: %s", cand, e)
                continue
            if r.status_code == 200 and r.content:
                content = r.content
                break
        if not content:
            return [], [], [f"Favicon pivot: could not fetch a favicon from {url}."]

        try:
            fhash = _favicon_hash(content)
        except Exception as e:  # noqa: BLE001
            return [], [], [f"Favicon pivot: hashing failed: {type(e).__name__}: {e}"]

        root = f"url:{url}"
        hlabel = str(fhash)
        findings.append(Finding(
            entity_type="favicon_hash", platform="shodan",
            label=hlabel, confidence=0.7,
            data={"favicon_hash": fhash, "source_url": url,
                  "host": parts.netloc.lower(),
                  "shodan_dork": f"http.favicon.hash:{fhash}", "source": "favicon"},
        ))
        edges.append(EdgeResult(from_entity=root,
                                to_entity=f"favicon_hash:{hlabel}",
                                relation="has_favicon", confidence=0.8))

        # 2) every host serving the same favicon → cluster around the hash.
        try:
            r = await client.get(f"{API}/shodan/host/search",
                                  params={"key": key,
                                          "query": f"http.favicon.hash:{fhash}"})
        except httpx.TimeoutException:
            errors.append("Shodan: favicon search timed out.")
            return findings, edges, errors
        if r.status_code == 401:
            errors.append("Shodan: SHODAN_API_KEY refused (401).")
            return findings, edges, errors
        if r.status_code == 403:
            # /shodan/host/search is a paid-membership endpoint; a free key
            # can only do single-host lookups. The favicon hash + dork are
            # still emitted, so this is a note (partial capability), not a
            # failure — paste the dork into a paid Shodan/Censys/FOFA.
            errors.append(f"{NOTE_PREFIX}Favicon hash computed ({fhash}), but "
                          "Shodan's host-search API — needed to list every host "
                          "sharing it — requires a PAID Shodan membership (free "
                          "keys only allow single-host lookups). Paste the dork "
                          f"`http.favicon.hash:{fhash}` into a paid Shodan / "
                          "Censys / FOFA account to cluster.")
            return findings, edges, errors
        if r.status_code != 200:
            errors.append(f"Shodan favicon search HTTP {r.status_code}.")
            return findings, edges, errors

        body = r.json() or {}
        matches = body.get("matches") or []
        total = body.get("total", len(matches))
        seen: set[str] = set()
        for m in matches[:MAX_FAVICON_HOSTS]:
            mip = m.get("ip_str")
            if not mip or mip in seen:
                continue
            seen.add(mip)
            findings.append(Finding(
                entity_type="ip", platform="shodan",
                label=mip, confidence=0.6,
                data={"ip": mip, "port": m.get("port"),
                      "org": (m.get("org") or ""),
                      "hostnames": m.get("hostnames") or [],
                      "country": (m.get("location") or {}).get("country_name", ""),
                      "via": "favicon", "source": "shodan"},
            ))
            edges.append(EdgeResult(from_entity=f"ip:{mip}",
                                    to_entity=f"favicon_hash:{hlabel}",
                                    relation="same_favicon", confidence=0.6))
        if total > len(seen):
            errors.append(f"{NOTE_PREFIX}Favicon shared by {total} hosts on Shodan; "
                          f"showing the first {len(seen)}.")
    return findings, edges, errors


# --- dom_hash_pivot --------------------------------------------------
#
# The sibling favicon_pivot needs, and the case it exists for: an operator
# who has been burned swaps the favicon — it is one file and the obvious
# thing to change — while the page itself, which IS the kit, stays byte
# identical across the whole deployment. Clustering on the markup catches
# what clustering on the icon just lost.
#
# ⚠️ **The two hashes are NOT computed the same way — established, not
# assumed.** Measured against a live Shodan banner (scanme.nmap.org,
# html_hash 1386351316):
#
#     favicon:  mmh3.hash(base64.encodebytes(icon_bytes))
#     html:     mmh3.hash(html_bytes)          ← no base64, raw body
#
# Guessing base64 here would have produced a confident, well-formed dork
# that silently matches nothing — the worst kind of wrong, because the
# empty result reads as "this kit is not deployed elsewhere".
#
# Verified in the same measurement: an ordinary direct fetch
# reproduces Shodan's hash exactly for a static page (same 6974 bytes, same
# hash). For a page that varies per request — a CSRF token, a timestamp, a
# rotating banner — it cannot, and the runner says so rather than presenting
# a dork that will come back empty.

# Below this, a body is a redirect stub or an error page, not a kit — and
# hashing it would cluster every host behind the same CDN error template.
MIN_HTML_BYTES = 512


async def run_dom_hash_pivot(
    query: str, query_type: str = "url", options: dict | None = None,
    job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    import mmh3  # lazy, as in _favicon_hash

    url = (query or "").strip()
    if not url:
        return [], [], ["DOM-hash pivot: empty url."]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        try:
            r = await client.get(url)
        except Exception as e:  # noqa: BLE001
            return [], [], [f"DOM-hash pivot: could not fetch {url}: "
                            f"{type(e).__name__}"]
        if r.status_code != 200 or not r.text:
            return [], [], [f"DOM-hash pivot: {url} answered HTTP "
                            f"{r.status_code} with no usable body."]
        body = r.text
        if len(body.encode()) < MIN_HTML_BYTES:
            return [], [], [f"{NOTE_PREFIX}DOM-hash pivot: {url} returned only "
                            f"{len(body.encode())} bytes — an interstitial or "
                            f"redirect stub, not a page worth fingerprinting."]

        dhash = mmh3.hash(body.encode())
        hlabel = str(dhash)
        root = f"url:{url}"
        findings.append(Finding(
            entity_type="dom_hash", platform="shodan",
            label=hlabel, confidence=0.7,
            data={"dom_hash": dhash, "source_url": url,
                  "host": urlsplit(str(r.url)).netloc.lower(),
                  "bytes": len(body.encode()),
                  "final_url": str(r.url),
                  "shodan_dork": f"http.html_hash:{dhash}",
                  "source": "dom_hash"},
        ))
        edges.append(EdgeResult(from_entity=root,
                                to_entity=f"dom_hash:{hlabel}",
                                relation="has_dom_hash", confidence=0.8))

        key = credential(options, "SHODAN_API_KEY")
        if not key:
            errors.append(f"{NOTE_PREFIX}DOM hash computed ({dhash}). Listing "
                          "every host serving the same page needs a Shodan key "
                          f"— paste `http.html_hash:{dhash}` into Shodan, "
                          "Censys or FOFA in the meantime.")
            return findings, edges, errors

        try:
            r2 = await client.get(f"{API}/shodan/host/search",
                                  params={"key": key,
                                          "query": f"http.html_hash:{dhash}"})
        except httpx.TimeoutException:
            errors.append("Shodan: DOM-hash search timed out.")
            return findings, edges, errors
        if r2.status_code == 401:
            errors.append("Shodan: SHODAN_API_KEY refused (401).")
            return findings, edges, errors
        if r2.status_code == 403:
            # Same paid-tier wall as favicon_pivot. The hash and the dork are
            # the durable part of the answer, so this is a note.
            errors.append(f"{NOTE_PREFIX}DOM hash computed ({dhash}), but "
                          "Shodan's host-search API — needed to list every host "
                          "serving the same page — requires a PAID Shodan "
                          f"membership. Paste `http.html_hash:{dhash}` into a "
                          "paid Shodan / Censys / FOFA account to cluster.")
            return findings, edges, errors
        if r2.status_code != 200:
            errors.append(f"Shodan DOM-hash search HTTP {r2.status_code}.")
            return findings, edges, errors

        body2 = r2.json() or {}
        matches = body2.get("matches") or []
        total = body2.get("total", len(matches))
        seen: set[str] = set()
        for m in matches[:MAX_FAVICON_HOSTS]:
            mip = m.get("ip_str")
            if not mip or mip in seen:
                continue
            seen.add(mip)
            findings.append(Finding(
                entity_type="ip", platform="shodan",
                label=mip, confidence=0.6,
                data={"ip": mip, "port": m.get("port"),
                      "org": (m.get("org") or ""),
                      "hostnames": m.get("hostnames") or [],
                      "country": (m.get("location") or {}).get("country_name", ""),
                      "via": "dom_hash", "source": "shodan"},
            ))
            edges.append(EdgeResult(from_entity=f"ip:{mip}",
                                    to_entity=f"dom_hash:{hlabel}",
                                    relation="same_dom", confidence=0.6))
        if total > len(seen):
            errors.append(f"{NOTE_PREFIX}Identical page served by {total} hosts "
                          f"on Shodan; showing the first {len(seen)}.")
    return findings, edges, errors
