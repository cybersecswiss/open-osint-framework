"""Can this domain be spoofed?

`dns_records` already fetches TXT/MX, and then says nothing about them. For a
phishing or BEC case that is the wrong stopping point: the question is not
"what TXT records exist" but **could mail claiming to come from this domain
have passed?** That is a judgement about three records, and it is one an
investigator otherwise has to make by hand from a raw string.

Three checks, keyless, all from DNS:

* **SPF** — present at all, and does it end in `-all` (hard fail), `~all`
  (softfail, mail still arrives) or `?all` / nothing (no statement)? A domain
  with `~all` is materially easier to spoof than one with `-all`, and that
  difference is exactly what decides whether a forged sender was plausible.
* **DMARC** — present, and is the policy `none` (monitor only), `quarantine`
  or `reject`? `p=none` is the common case and it means the SPF/DKIM result is
  observed and then ignored.
* **DKIM** — probe the common selectors. A hit proves signing is configured;
  no hit proves nothing (selectors are arbitrary), and this says so rather
  than reporting an absence it cannot establish.

Ratings are deliberately conservative: the finding states what the records
say, never "this mail was forged".
"""
from __future__ import annotations

import asyncio
import logging

from schemas import EdgeResult, Finding, NOTE_PREFIX

log = logging.getLogger("module-infra")

DNS_TIMEOUT = 5.0

# Selectors worth probing. Not a guess at the domain's own naming — these are
# the defaults the big providers install, so a hit is common and a miss is
# meaningless.
COMMON_SELECTORS = [
    "default", "google", "selector1", "selector2", "k1", "k2",
    "mail", "dkim", "smtp", "s1", "s2", "mandrill", "zoho", "protonmail",
]


def _clean(domain: str) -> str:
    d = (domain or "").strip().lower()
    for prefix in ("http://", "https://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split("/")[0].split(":")[0].strip(".")


async def _txt(name: str) -> list[str]:
    """TXT lookup that treats 'no record' and 'lookup failed' as the same
    empty answer — the caller must not report a resolver hiccup as 'the
    domain has no SPF'."""
    import dns.asyncresolver

    try:
        res = dns.asyncresolver.Resolver()
        res.lifetime = DNS_TIMEOUT
        answers = await res.resolve(name, "TXT")
        return [b"".join(r.strings).decode("utf-8", "replace") for r in answers]
    except Exception:  # noqa: BLE001
        return []


def _spf_verdict(record: str) -> tuple[str, str]:
    """(policy, plain-language meaning) from the record's `all` mechanism."""
    r = record.lower()
    if "-all" in r:
        return "hard fail", "unauthorised senders are rejected"
    if "~all" in r:
        return "soft fail", "unauthorised senders are accepted and only marked"
    if "?all" in r:
        return "neutral", "the domain makes no statement about unauthorised senders"
    if "+all" in r:
        return "pass all", "ANY sender is authorised — the record protects nothing"
    return "no all-mechanism", "the record does not say what to do with unauthorised senders"


async def run_email_security(
    query: str, query_type: str = "domain", job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    domain = _clean(query)
    if not domain or "." not in domain:
        return [], [], ["email_security: provide a domain."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    dom_key = f"domain:{domain}"

    spf_txt, dmarc_txt = await asyncio.gather(
        _txt(domain), _txt(f"_dmarc.{domain}"))

    # ── SPF ──────────────────────────────────────────────────────────
    spf = next((t for t in spf_txt if t.lower().startswith("v=spf1")), None)
    if spf:
        policy, meaning = _spf_verdict(spf)
        findings.append(Finding(
            entity_type="email_policy", platform="spf", label=f"SPF: {policy} ({domain})",
            url=f"https://mxtoolbox.com/SuperTool.aspx?action=spf%3a{domain}",
            confidence=0.95,
            data={"domain": domain, "record": spf, "policy": policy,
                  "meaning": meaning, "source": "dns_txt"},
        ))
    else:
        findings.append(Finding(
            entity_type="email_policy", platform="spf", label=f"SPF: absent ({domain})",
            confidence=0.9,
            data={"domain": domain, "policy": "absent",
                  "meaning": "no sender policy published — anyone may send as this domain",
                  "source": "dns_txt"},
        ))
    edges.append(EdgeResult(from_entity=dom_key,
                            to_entity=f"email_policy:{findings[-1].label}",
                            relation="mail_policy", confidence=0.95))

    # ── DMARC ────────────────────────────────────────────────────────
    dmarc = next((t for t in dmarc_txt if "v=dmarc1" in t.lower()), None)
    if dmarc:
        low = dmarc.lower()
        pol = ("reject" if "p=reject" in low else
               "quarantine" if "p=quarantine" in low else
               "none" if "p=none" in low else "unspecified")
        meaning = {
            "reject": "failing mail is rejected",
            "quarantine": "failing mail goes to spam",
            "none": "failures are only reported — nothing is blocked",
            "unspecified": "no policy given in the record",
        }[pol]
        findings.append(Finding(
            entity_type="email_policy", platform="dmarc",
            label=f"DMARC: p={pol} ({domain})",
            url=f"https://mxtoolbox.com/SuperTool.aspx?action=dmarc%3a{domain}",
            confidence=0.95,
            data={"domain": domain, "record": dmarc, "policy": pol,
                  "meaning": meaning, "source": "dns_txt"},
        ))
    else:
        findings.append(Finding(
            entity_type="email_policy", platform="dmarc",
            label=f"DMARC: absent ({domain})", confidence=0.9,
            data={"domain": domain, "policy": "absent",
                  "meaning": "no DMARC — SPF/DKIM results are not enforced",
                  "source": "dns_txt"},
        ))
    edges.append(EdgeResult(from_entity=dom_key,
                            to_entity=f"email_policy:{findings[-1].label}",
                            relation="mail_policy", confidence=0.95))

    # ── DKIM ─────────────────────────────────────────────────────────
    found = [sel for sel, txts in zip(
        COMMON_SELECTORS,
        await asyncio.gather(*[_txt(f"{s}._domainkey.{domain}")
                               for s in COMMON_SELECTORS]))
        if txts]
    if found:
        findings.append(Finding(
            entity_type="email_policy", platform="dkim",
            label=f"DKIM: {len(found)} selector(s) ({domain})", confidence=0.9,
            data={"domain": domain, "selectors": found,
                  "meaning": "mail from this domain is signed",
                  "source": "dns_txt"},
        ))
        edges.append(EdgeResult(from_entity=dom_key,
                                to_entity=f"email_policy:{findings[-1].label}",
                                relation="mail_policy", confidence=0.9))
    else:
        # Deliberately a note, not a finding: DKIM selectors are arbitrary
        # strings, so probing the common ones cannot establish an absence.
        errors.append(f"{NOTE_PREFIX}DKIM: none of the {len(COMMON_SELECTORS)} "
                      f"common selectors answered. Selectors are arbitrary, so "
                      f"this does NOT mean the domain is unsigned.")

    return findings, edges, errors
