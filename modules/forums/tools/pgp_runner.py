"""
PGP keyserver lookup — a cybercrime deanonymisation pivot.

Threat actors reuse the same OpenPGP key across forums, markets and years.
A handle changes; the key fingerprint does not. Resolving a key both ways
is one of the most stable cross-identity links available:

  * email        → the key(s) that carry that email as a UID
                   → EVERY OTHER email/name on the same key (deanon).
  * pgp_fingerprint → all UIDs (emails + names) bound to that key.

Keyless: uses the public hockeypuck keyserver at keyserver.ubuntu.com in
machine-readable index mode (`op=index&options=mr`), which returns pub/uid
records without downloading full key material.

Graph convention (graph_builder): a Finding's `label` carries the
`{entity_type}:` prefix; each edge endpoint is the same `etype:label`
string; the root is `f"{query_type}:{query}"`. `email` nodes dedupe with
holehe/leakcheck/linkook, so a PGP-derived email is immediately pivotable.
"""
from __future__ import annotations

import re
import urllib.parse

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX

KEYSERVER = "https://keyserver.ubuntu.com/pks/lookup"
TIMEOUT = 20.0
# Keyserver UIDs are UNVERIFIED (anyone can upload a key with any UID) and
# come in inconsistent orderings, so never trust the `<>` position — pull
# the email out by shape and treat the remainder as the name.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _parse_uid(raw: str) -> tuple[str, str]:
    """(name, email) from a UID string, robust to ordering/spoofed UIDs."""
    em = _EMAIL_RE.search(raw)
    email = em.group(0).lower() if em else ""
    name = raw
    if em:
        name = raw.replace(em.group(0), "")
    name = name.strip(" <>()\t").strip()
    return name, email


def _norm_fpr(s: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", s or "").upper()


async def _index(search: str) -> tuple[list[dict], list[str]]:
    """Return parsed keys [{fpr, algo, created, uids:[{name,email}]}] from
    the keyserver machine-readable index for `search`."""
    params = {"op": "index", "options": "mr", "search": search, "fingerprint": "on"}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as c:
        r = await c.get(KEYSERVER, params=params,
                        headers={"User-Agent": "OOF/1.0"})
    if r.status_code == 404:
        return [], []
    if r.status_code != 200:
        return [], [f"keyserver HTTP {r.status_code}"]

    keys: list[dict] = []
    cur: dict | None = None
    for line in r.text.splitlines():
        parts = line.split(":")
        tag = parts[0]
        if tag == "pub" and len(parts) >= 6:
            cur = {"fpr": _norm_fpr(parts[1]), "algo": parts[2],
                   "created": parts[4], "uids": []}
            keys.append(cur)
        elif tag == "uid" and cur is not None and len(parts) >= 2:
            raw = urllib.parse.unquote(parts[1]).strip()
            name, email = _parse_uid(raw)
            if email or name:
                cur["uids"].append({"name": name, "email": email, "raw": raw})
    return keys, []


async def run_pgp_lookup(
    query: str, query_type: str, options: dict | None = None
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    q = (query or "").strip()
    if not q:
        return findings, edges, ["Empty query."]

    if query_type == "pgp_fingerprint":
        search = "0x" + _norm_fpr(q)
        root = f"pgp_fingerprint:{q}"
    elif query_type == "email":
        search = q
        root = f"email:{q}"
    else:
        return findings, edges, [f"pgp_lookup: unsupported query_type {query_type}"]

    try:
        keys, errs = await _index(search)
    except httpx.HTTPError as e:
        return findings, edges, [f"keyserver unreachable: {type(e).__name__}: {e}"]
    errors.extend(errs)

    seen_email: set[str] = set()

    for k in keys:
        fpr = k["fpr"]
        if not fpr:
            continue
        key_node = f"pgp_key:{fpr}"

        if query_type == "email":
            # email → key: create the key node and hang it off the email root.
            findings.append(Finding(
                entity_type="pgp_key", platform="keyserver", label=key_node,
                confidence=0.9,
                data={"fingerprint": fpr, "algo": k["algo"], "created": k["created"],
                      "uid_count": len(k["uids"]), "source": "keyserver.ubuntu.com"},
            ))
            edges.append(EdgeResult(from_entity=root, to_entity=key_node,
                                    relation="uses_pgp_key", confidence=0.9))
            parent = key_node  # other UIDs hang off the key
        else:
            # fingerprint query: UIDs hang directly off the fingerprint root.
            parent = root

        for uid in k["uids"]:
            email = uid["email"].lower()
            name = uid["name"]
            if email and email not in seen_email:
                seen_email.add(email)
                # don't re-emit the very email we searched for as a child
                if not (query_type == "email" and email == q.lower()):
                    findings.append(Finding(
                        entity_type="email", platform="pgp", label=f"email:{email}",
                        confidence=0.85,
                        data={"via": "pgp_uid", "pgp_fingerprint": fpr,
                              "name": name or None, "source": "keyserver"},
                    ))
                    edges.append(EdgeResult(from_entity=parent, to_entity=f"email:{email}",
                                            relation="pgp_uid", confidence=0.85))
            if name and len(name) > 1:
                pnode = f"person:{name}"
                findings.append(Finding(
                    entity_type="person", platform="pgp", label=pnode,
                    confidence=0.6,
                    data={"via": "pgp_uid", "pgp_fingerprint": fpr,
                          "email": email or None, "source": "keyserver"},
                ))
                edges.append(EdgeResult(from_entity=parent, to_entity=pnode,
                                        relation="pgp_uid", confidence=0.6))

    if not findings and not errors:
        errors.append(NOTE_PREFIX + f"No PGP key found for {q} on keyserver.ubuntu.com.")
    return findings, edges, errors
