"""Investigation playbooks — module presets per offence type.

Today the search form asks the investigator to pick *modules*. That presumes
they know that `forums` contributes to a ransomware case and that `compliance`
is worth running on a crypto-fraud selector. Nobody knows that on their first
week, and the cost of not knowing is a search that quietly misses the source
that would have cracked the case.

A playbook is also a **case template**: a case created with
one (`cases.template`) gets it preselected in its search form, a report
outline to match (`report_sections`) and its typical next tools shown.

A playbook is the same search with the domain knowledge already applied: the
module set, the query types it makes sense for, and the follow-up steps that
usually come next. Deliberately configuration and nothing else — no new
collection code, no new orchestration path. The investigator can still
override every module afterwards; the playbook only sets the starting point.

`query_types` lists the selectors the playbook is meaningful for. The UI uses
it to grey out a playbook that cannot apply to what was typed — offering
"Ransomware incident" for a BTC address and then running username tools on it
is worse than not offering it at all.

`modules` names must exist in MODULE_REGISTRY; unknown ones are filtered at
serve time rather than 500-ing a search later, so a playbook stays valid when
a tenant is not licensed for one of its modules.
"""
from __future__ import annotations

from typing import Any

# Ordered: most common offence types first, because the list is a menu and
# the top of a menu is where people look.
PLAYBOOKS: list[dict[str, Any]] = [
    {
        # Sanctions evasion / procurement networks: a front company buys
        # controlled goods for an end user who may not appear anywhere on the
        # paperwork. The chain that exposes it runs register → ownership →
        # sanctions list → the infrastructure the front actually uses.
        "key": "procurement_network",
        "modules": ["corporate", "compliance", "infra", "news", "leaks"],
        "query_types": ["company_name", "person_name", "keyword", "domain", "email"],
        "next_steps": ["shab_registry", "gleif_lei", "sanctions_screen",
                       "wikidata_entity", "theharvester"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "graph_snapshot", "searches", "activity", "evidence", "captures"],
    },
    {
        "key": "ransomware",
        "modules": ["threat", "infra", "darknet", "forums", "leaks"],
        "query_types": ["domain", "ip", "keyword", "url", "hash"],
        "next_steps": ["ransomware_watch", "passive_dns", "asn_lookup", "cve_lookup"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "graph_snapshot", "timeline", "searches", "activity", "alerts", "evidence", "captures"],
    },
    {
        "key": "phishing",
        # dnstwist + crt.sh find the look-alikes; threat rates the URLs;
        # infra ties them to hosting.
        "modules": ["infra", "threat", "news"],
        "query_types": ["domain", "url", "ip"],
        "next_steps": ["dnstwist", "crtsh", "urlscan", "passive_dns"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "searches", "activity", "alerts", "evidence", "captures"],
    },
    {
        "key": "darknet_trade",
        "modules": ["darknet", "forums", "crypto", "messenger", "telegram"],
        "query_types": ["keyword", "username", "btc_address",
                        "pgp_fingerprint", "jabber_id"],
        "next_steps": ["ahmia", "crime_forum_hunt", "pgp_lookup"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "graph_snapshot", "timeline", "searches", "activity", "evidence", "captures"],
    },
    {
        "key": "fraud_shop",
        "modules": ["infra", "threat", "compliance", "news"],
        "query_types": ["domain", "url", "keyword", "email"],
        "next_steps": ["whois", "crtsh", "passive_dns", "opensanctions"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "searches", "activity", "evidence", "captures"],
    },
    {
        "key": "crypto_fraud",
        "modules": ["crypto", "compliance", "forums", "darknet"],
        "query_types": ["btc_address", "eth_address", "keyword"],
        "next_steps": ["blockchain_btc", "wallet_attribution", "opensanctions"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "graph_snapshot", "timeline", "searches", "activity", "evidence", "captures"],
    },
    {
        "key": "sextortion",
        # Identity-side first: the selector is usually an account or an
        # address, and the leak modules establish what the actor already had.
        "modules": ["alias", "leaks", "messenger", "telegram"],
        "query_types": ["username", "email", "phone", "tg_channel"],
        "next_steps": ["sherlock", "holehe", "hudsonrock", "telegram_username_hunt"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "timeline", "searches", "activity", "evidence", "captures"],
    },
    {
        "key": "infrastructure",
        "modules": ["infra", "threat"],
        "query_types": ["domain", "ip", "asn", "url"],
        "next_steps": ["passive_dns", "asn_lookup", "shodan_host", "crtsh"],
        "report_sections": ["cover", "summary", "key_findings", "entities_table", "relationships", "graph_snapshot", "searches", "activity", "alerts", "evidence", "captures"],
    },
]


def for_query_type(
    query_type: str | None,
    available_modules: set[str],
) -> list[dict[str, Any]]:
    """Playbooks the caller can actually run, in display order.

    Modules the tenant is not licensed for (or that are unreachable) are
    stripped from each entry rather than hiding the whole playbook — a
    ransomware case without the `forums` module is still worth running, it
    just covers less. A playbook left with no runnable module is dropped.
    """
    out: list[dict[str, Any]] = []
    for pb in PLAYBOOKS:
        modules = [m for m in pb["modules"] if m in available_modules]
        if not modules:
            continue
        entry = {
            "key": pb["key"],
            "modules": modules,
            "query_types": pb["query_types"],
            "next_steps": pb["next_steps"],
            "report_sections": pb.get("report_sections") or [],
            "applies": query_type is None or query_type in pb["query_types"],
            # Say when the preset is not the full playbook, so nobody reads a
            # narrower run as the complete one.
            "unavailable_modules": [m for m in pb["modules"] if m not in available_modules],
        }
        out.append(entry)
    return out


PLAYBOOK_KEYS = frozenset(pb["key"] for pb in PLAYBOOKS)
