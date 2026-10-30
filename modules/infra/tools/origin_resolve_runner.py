"""Origin resolution — the real address behind a CDN.

What the category usually means, and what this actually is
----------------------------------------------------------
"Resolver" in the criminal-OSINT scene covers three unrelated things. Two of
them do not work and are not built here:

* **Skype resolver.** Skype leaked peer addresses because it was a P2P
  protocol. Microsoft moved it to server relays years ago and retired Skype
  itself in May 2025. Every site still offering this returns fabricated data.
* **PSN / Xbox / Discord "IP resolver".** Console and Discord traffic runs
  through platform relays; a user id has not mapped to a client address in
  years. These sites monetise the belief that it does.

The third one is real, is standard infrastructure work, and is what this
runner does: **a site behind Cloudflare still runs somewhere.** Finding that
address turns "a phishing kit on Cloudflare" into "a phishing kit on this
host, at this provider, next to these other domains" — which is where an
infrastructure case actually starts, and what `passive_dns`, `asn_lookup` and
`shodan_host` can then be pivoted from.

Why the answer has to be verified, not merely collected
-------------------------------------------------------
Every published technique for this produces CANDIDATES: an old A record, a
mail server, an SPF literal, a forgotten `dev.` subdomain. Any of them may be
a shared host, a parked address, the CDN's own edge, or simply stale. Handing
those to an investigator as "the origin" is exactly the failure mode this
project keeps finding in other people's tools — a plausible answer that
cannot be checked.

So each candidate is PROVEN or dropped:

1. **Baseline.** Fetch the site normally, through the CDN. That is what the
   origin must be able to reproduce.
2. **Direct probe.** Fetch ``http://<candidate>/`` with ``Host: <domain>``.
   If the candidate is the origin, the vhost answers with the same page.
3. **Negative control.** Fetch the same address with a Host header that
   cannot exist (``<random>.invalid``). A server that answers identically for
   any Host is a catch-all — shared hosting, a default vhost, a parking page
   — and proves nothing about THIS domain. Same two-gate logic as
   ``modules/base/verifier.py``, for the same reason.

A candidate that fails either gate is discarded and COUNTED. The count goes
out as a note, so "3 of 47 candidates verified" is visible rather than
looking like a thin result.

Deliberate limits, stated rather than implied
---------------------------------------------
* **If the domain is not behind a recognised CDN, this returns nothing and
  says so.** The A record already IS the origin; inventing work there would
  produce findings that restate the input.
* **HTTPS to a bare IP is attempted with certificate verification off.** The
  certificate cannot match an IP the CDN fronts, so verifying it would reject
  every true positive. This is safe here precisely because nothing in the
  response is trusted: it is hashed and compared, never parsed as truth.
  Plain HTTP is tried first for the same reason it usually works — origins
  behind a CDN are commonly configured to serve cleartext to the edge.
* **A negative is not proof of absence.** An origin that filters everything
  except the CDN's ranges — the correct configuration — is invisible to this
  method, and that is stated in the note rather than reported as "no origin".
* ⚠️ **This probes the target directly from the operator's address.** Unlike
  the forum sweep it does NOT go through Tor: the whole method depends on
  presenting a chosen Host header to a chosen address, which the Tor path
  here is not built for. For a live adversary infrastructure that is a
  disclosure, and whoever runs it should know that. `favicon_pivot` and
  `dom_hash_pivot` already carry the same property.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
import secrets
from typing import Any, Iterable

import httpx

from safe_fetch import _ip_is_blocked
from schemas import NOTE_PREFIX, EdgeResult, Finding

log = logging.getLogger("module-infra.origin_resolve")

USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 20
BASELINE_TIMEOUT = 25

# Published edge ranges. Fetched live so a provider's growth does not silently
# turn edge addresses into "origin candidates" — the failure mode of every
# hardcoded CDN list.
CDN_RANGE_SOURCES: dict[str, tuple[str, str]] = {
    "cloudflare-v4": ("https://www.cloudflare.com/ips-v4", "text"),
    "cloudflare-v6": ("https://www.cloudflare.com/ips-v6", "text"),
    "fastly":        ("https://api.fastly.com/public-ip-list", "fastly"),
    "cloudfront":    ("https://d7uri8nf7uskq.cloudfront.net/tools/list-cloudfront-ips",
                      "cloudfront"),
}

MAX_SUBDOMAIN_PROBES = 40      # crt.sh names we are willing to resolve
MAX_CANDIDATES = 25            # candidates we are willing to probe
PROBE_CONCURRENCY = 6

# The cap above bites hard — on a large site the four axes easily produce
# hundreds of candidates for 25 probe slots. WHICH 25 therefore decides
# whether the tool answers, and taking them in discovery order would hand the
# slots to whichever axis happened to run first.
#
# This is the same defect `hunt_order()` had in the forum pool: a cap applied
# to an unordered list looks like coverage and is a coin toss. So candidates
# are ranked by how strongly their SOURCE implies the origin:
#
#   0  SPF literal      — the domain itself publishes "these addresses are
#                         mine". No inference at all.
#   1  MX host          — port 25 is not proxied by a web CDN, so the mail
#                         host is frequently the same machine.
#   2  origin-typical subdomain — `direct.`, `origin.`, `cpanel.`, `mail.`:
#                         named by an admin who needed to bypass the edge.
#   3  any other subdomain — one forgotten host on the same box.
#   4  historical A record — was true once; the weakest, because "moved
#                         behind a CDN" and "moved hosts entirely" look the
#                         same from here.
#
# Ties keep discovery order, which is stable across runs.
PRIO_SPF, PRIO_MX, PRIO_HINT_SUB, PRIO_SUB, PRIO_HISTORY = 0, 1, 2, 3, 4

# Subdomains that historically sit on the origin rather than the edge. Ordered:
# the crt.sh list is capped, and these should make the cut first.
_ORIGIN_HINTS = ("direct", "origin", "cpanel", "webmail", "mail", "smtp", "ftp",
                 "dev", "staging", "test", "old", "backup", "vpn", "portal")

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# --------------------------------------------------------------- CDN ranges
async def _load_cdn_ranges(client: httpx.AsyncClient) -> tuple[list[Any], list[str]]:
    nets: list[Any] = []
    errors: list[str] = []
    for name, (url, fmt) in CDN_RANGE_SOURCES.items():
        try:
            r = await client.get(url, timeout=15)
            if r.status_code != 200:
                errors.append(f"{name} HTTP {r.status_code}")
                continue
            if fmt == "text":
                raw = r.text.split()
            elif fmt == "fastly":
                d = r.json()
                raw = list(d.get("addresses", [])) + list(d.get("ipv6_addresses", []))
            else:  # cloudfront
                d = r.json()
                raw = (list(d.get("CLOUDFRONT_GLOBAL_IP_LIST", []))
                       + list(d.get("CLOUDFRONT_REGIONAL_EDGE_IP_LIST", [])))
            for cidr in raw:
                try:
                    nets.append(ipaddress.ip_network(cidr.strip(), strict=False))
                except ValueError:
                    continue
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}")
    return nets, errors


def _in_cdn(addr: str, nets: Iterable[Any]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in n for n in nets if ip.version == n.version)


# ------------------------------------------------------------------- DNS
def _dns(name: str, rtype: str) -> list[str]:
    import dns.resolver  # lazy, matches dns_runner

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 6.0
    resolver.timeout = 3.0
    try:
        answer = resolver.resolve(name, rtype)
    except Exception:  # noqa: BLE001 — absence is normal, never fatal here
        return []
    out = []
    for r in answer:
        if rtype == "MX":
            out.append(str(r.exchange).rstrip("."))
        else:
            out.append(str(r).strip('"').rstrip("."))
    return out


async def _dns_async(name: str, rtype: str) -> list[str]:
    return await asyncio.to_thread(_dns, name, rtype)


def _spf_literals(txt_records: list[str]) -> list[str]:
    """`ip4:` / `ip6:` mechanisms from an SPF record.

    SPF is a domain publishing, in its own words, which addresses send its
    mail. Behind a CDN those are commonly the origin's own addresses — the
    operator has to list them, and the CDN does not proxy port 25.
    """
    out: list[str] = []
    for rec in txt_records:
        if "v=spf1" not in rec.lower():
            continue
        for token in rec.split():
            for prefix in ("ip4:", "ip6:"):
                if token.lower().startswith(prefix):
                    val = token[len(prefix):]
                    try:
                        net = ipaddress.ip_network(val, strict=False)
                    except ValueError:
                        continue
                    # A /24 of candidates is not a candidate. Only take
                    # literals precise enough to probe.
                    if net.num_addresses <= 4:
                        out.extend(str(a) for a in net.hosts() or [net.network_address])
    return out


# ------------------------------------------------------------- comparison
def _signature(status: int, body: str) -> tuple[int, str, str, int]:
    """(status, title, text-hash, length) — what makes two pages 'the same'."""
    m = _TITLE.search(body or "")
    title = _WS.sub(" ", _TAGS.sub("", m.group(1))).strip().lower()[:120] if m else ""
    text = _WS.sub(" ", _TAGS.sub(" ", body or "")).strip().lower()
    return status, title, hashlib.sha256(text[:4000].encode()).hexdigest(), len(text)


def _same_page(a: tuple[int, str, str, int], b: tuple[int, str, str, int]) -> tuple[bool, str]:
    if a[2] == b[2] and a[2]:
        return True, "identical body"
    if a[1] and a[1] == b[1]:
        return True, f"identical title ({a[1][:60]!r})"
    # A dynamic page (session ids, timestamps, ads) differs byte-wise while
    # being the same site. Length within 10% plus the same status is weak on
    # its own, so it only counts when the page is substantial.
    if a[0] == b[0] and a[3] > 500 and b[3] > 500:
        ratio = min(a[3], b[3]) / max(a[3], b[3])
        if ratio >= 0.9:
            return True, f"same status and body length within {(1-ratio)*100:.0f}%"
    return False, ""


async def _probe(client: httpx.AsyncClient, ip: str, host: str
                 ) -> tuple[tuple[int, str, str, int] | None, str | None]:
    """Fetch ip with an explicit Host header. Returns (signature, scheme)."""
    bracket = f"[{ip}]" if ":" in ip else ip
    for scheme in ("http", "https"):
        try:
            r = await client.get(f"{scheme}://{bracket}/",
                                 headers={"Host": host}, timeout=TIMEOUT)
        except Exception:  # noqa: BLE001 — closed port / TLS refusal is normal
            continue
        if r.status_code >= 500:
            continue
        return _signature(r.status_code, r.text), scheme
    return None, None


def _rank(cands: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Strongest-source-first. Python's sort is stable, so equal ranks keep
    discovery order and the selection is reproducible across runs."""
    return sorted(cands.items(), key=lambda kv: kv[1]["prio"])


# ------------------------------------------------------------------ main
async def run_origin_resolve(
    query: str, query_type: str, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    domain = (query or "").strip().lower()
    if query_type == "url" or domain.startswith(("http://", "https://")):
        domain = httpx.URL(domain if "://" in domain else f"http://{domain}").host or ""
    domain = domain.strip().rstrip(".").removeprefix("www.")
    if not domain or "." not in domain:
        return [], [], ["origin_resolve: no usable domain in query"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    root = f"domain:{domain}"

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers, verify=False,
                                 follow_redirects=True) as client:
        nets, range_errors = await _load_cdn_ranges(client)
        if not nets:
            return findings, edges, [
                "origin_resolve: could not load any CDN address list "
                f"({'; '.join(range_errors) or 'no source answered'}) — refusing "
                "to run, because without them every edge address would be "
                "reported as an origin candidate."]
        if range_errors:
            errors.append(f"{NOTE_PREFIX}origin_resolve: "
                          f"{len(CDN_RANGE_SOURCES) - len(range_errors)} of "
                          f"{len(CDN_RANGE_SOURCES)} CDN lists loaded "
                          f"({'; '.join(range_errors)}).")

        # ---- 1. is it fronted at all? -------------------------------------
        current = await _dns_async(domain, "A") + await _dns_async(domain, "AAAA")
        current = [a for a in current if not _ip_is_blocked(a)]
        if not current:
            return findings, edges, [
                f"{NOTE_PREFIX}origin_resolve: '{domain}' has no public A/AAAA "
                "record — nothing to resolve behind."]
        fronted = [a for a in current if _in_cdn(a, nets)]
        if not fronted:
            return findings, edges, [
                f"{NOTE_PREFIX}origin_resolve: '{domain}' does not resolve into any "
                f"known CDN range ({', '.join(current[:4])}) — its A record already "
                "IS the origin, so there is nothing hidden to find. Use "
                "passive_dns or shodan_host for that address instead."]

        # ---- 2. baseline through the CDN ---------------------------------
        try:
            r = await client.get(f"https://{domain}/", timeout=BASELINE_TIMEOUT)
            baseline = _signature(r.status_code, r.text)
        except Exception as e:  # noqa: BLE001
            return findings, edges, [
                f"origin_resolve: the site itself is unreachable through the CDN "
                f"({type(e).__name__}) — without a baseline page no candidate can "
                "be proven, so nothing is reported."]
        if baseline[3] < 200:
            errors.append(f"{NOTE_PREFIX}origin_resolve: the CDN-served page is nearly "
                          "empty (challenge or block page) — comparison is weak, "
                          "only exact body/title matches will be accepted.")

        # ---- 3. gather candidates ----------------------------------------
        cands: dict[str, dict[str, Any]] = {}   # ip -> {reasons, prio}

        def add(ip: str, why: str, prio: int) -> None:
            if not ip or _ip_is_blocked(ip) or _in_cdn(ip, nets):
                return
            c = cands.setdefault(ip, {"reasons": [], "prio": prio})
            if why not in c["reasons"]:
                c["reasons"].append(why)
            # An address surfaced by two axes keeps the STRONGER claim: being
            # both an MX and an old A record is better evidence than either.
            c["prio"] = min(c["prio"], prio)

        txt = await _dns_async(domain, "TXT")
        for ip in _spf_literals(txt):
            add(ip, "SPF ip4/ip6 literal", PRIO_SPF)

        for mx in (await _dns_async(domain, "MX"))[:5]:
            for ip in await _dns_async(mx, "A"):
                add(ip, f"MX {mx}", PRIO_MX)

        try:
            r = await client.get("https://crt.sh/", timeout=45,
                                 params={"q": f"%.{domain}", "output": "json"})
            names: set[str] = set()
            if r.status_code == 200:
                for row in r.json():
                    for n in str(row.get("name_value", "")).splitlines():
                        n = n.strip().lower().lstrip("*.").rstrip(".")
                        if n.endswith(domain) and n != domain:
                            names.add(n)
            ordered = sorted(names, key=lambda n: (
                not any(n.startswith(h + ".") for h in _ORIGIN_HINTS), len(n)))
            if len(ordered) > MAX_SUBDOMAIN_PROBES:
                errors.append(f"{NOTE_PREFIX}origin_resolve: crt.sh listed "
                              f"{len(ordered)} names, resolved the first "
                              f"{MAX_SUBDOMAIN_PROBES} (origin-typical prefixes first).")
            for n in ordered[:MAX_SUBDOMAIN_PROBES]:
                hinted = any(n.startswith(h + ".") for h in _ORIGIN_HINTS)
                for ip in await _dns_async(n, "A"):
                    add(ip, f"subdomain {n}",
                        PRIO_HINT_SUB if hinted else PRIO_SUB)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{NOTE_PREFIX}origin_resolve: crt.sh unavailable "
                          f"({type(e).__name__}) — subdomain axis skipped.")

        try:
            r = await client.get(f"https://api.mnemonic.no/pdns/v3/{domain}",
                                 params={"limit": 300}, timeout=30)
            if r.status_code == 200:
                for rec in (r.json().get("data") or []):
                    if str(rec.get("rrtype", "")).lower() in ("a", "aaaa") \
                            and str(rec.get("query", "")).lower().rstrip(".") == domain:
                        add(str(rec.get("answer", "")).strip(),
                            "historical A record", PRIO_HISTORY)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{NOTE_PREFIX}origin_resolve: passive DNS unavailable "
                          f"({type(e).__name__}) — history axis skipped.")

        if not cands:
            return findings, edges, errors + [
                f"{NOTE_PREFIX}origin_resolve: '{domain}' is behind a CDN and no "
                "candidate address surfaced from SPF, MX, certificate transparency "
                "or passive DNS. That is the expected result for a site that was "
                "never exposed — it is not evidence that no origin exists."]

        ranked = _rank(cands)
        probe_list = [(ip, c["reasons"]) for ip, c in ranked[:MAX_CANDIDATES]]
        if len(cands) > MAX_CANDIDATES:
            dropped = ranked[MAX_CANDIDATES:]
            weakest_probed = ranked[MAX_CANDIDATES - 1][1]["prio"]
            errors.append(
                f"{NOTE_PREFIX}origin_resolve: {len(cands)} candidates found, probed the "
                f"{MAX_CANDIDATES} strongest (SPF → MX → origin-typical subdomain → "
                f"subdomain → DNS history). {len(dropped)} unprobed, all at or below "
                f"rank {weakest_probed} — re-run after narrowing if one of them matters.")

        # ---- 4. prove or drop --------------------------------------------
        sem = asyncio.Semaphore(PROBE_CONCURRENCY)
        control_host = f"{secrets.token_hex(8)}.invalid"

        async def verify(ip: str, reasons: list[str]) -> dict[str, Any] | None:
            async with sem:
                sig, scheme = await _probe(client, ip, domain)
                if sig is None:
                    return {"ip": ip, "verdict": "no answer"}
                ok, why = _same_page(baseline, sig)
                if not ok:
                    return {"ip": ip, "verdict": "serves a different site"}
                ctrl, _ = await _probe(client, ip, control_host)
                if ctrl is not None and _same_page(sig, ctrl)[0]:
                    return {"ip": ip, "verdict": "catch-all (same page for any Host)"}
                return {"ip": ip, "verdict": "confirmed", "why": why,
                        "scheme": scheme, "reasons": reasons,
                        "control": "answered differently" if ctrl else "no answer"}

        results = await asyncio.gather(*(verify(ip, w) for ip, w in probe_list))

    confirmed = [r for r in results if r and r.get("verdict") == "confirmed"]
    rejected = [r for r in results if r and r.get("verdict") != "confirmed"]

    for r in confirmed:
        findings.append(Finding(
            entity_type="ip", label=r["ip"], confidence=0.85, platform="origin_resolve",
            data={
                "role": "origin_server",
                "fronted_by": ", ".join(sorted({f"{a}" for a in fronted})[:3]),
                "evidence": r["why"],
                "negative_control": r["control"],
                "reached_over": r["scheme"],
                "surfaced_by": r["reasons"],
            },
        ))
        edges.append(EdgeResult(
            from_entity=f"ip:{r['ip']}", to_entity=root,
            relation="origin_server", confidence=0.85,
        ))

    if rejected:
        by_verdict: dict[str, int] = {}
        for r in rejected:
            by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
        errors.append(f"{NOTE_PREFIX}origin_resolve: {len(confirmed)} of "
                      f"{len(results)} candidates confirmed; dropped — "
                      + ", ".join(f"{n}× {v}" for v, n in sorted(by_verdict.items())) + ".")
    if not confirmed:
        errors.append(f"{NOTE_PREFIX}origin_resolve: no candidate reproduced the site. "
                      "An origin that only accepts connections from the CDN's own "
                      "ranges — the correct configuration — cannot be found this way, "
                      "so this is not evidence that none exists.")
    return findings, edges, errors
