import os
import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.crtsh_runner import run_crtsh
from tools.dns_runner import run_dns_records
from tools.email_security_runner import run_email_security
from tools.dnstwist_runner import run_dnstwist
from tools.passive_dns_runner import run_passive_dns
from tools.origin_resolve_runner import run_origin_resolve
from tools.asn_runner import run_asn
from tools.shodan_runner import (
    run_dom_hash_pivot, run_favicon_pivot, run_shodan_host,
)
from tools.subfinder_runner import run_subfinder
from tools.theharvester_runner import run_theharvester
from tools.whois_runner import run_whois

app = FastAPI(title="OSINT Module: Infrastructure", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="infra",
    label_key="search.module_infra",
    category="infrastructure",
    description_key="search.module_infra_desc",
    tools=[
        ToolDescriptor(
            tool="subfinder",
            reliability="C",
            label_key="search.tool_subfinder",
            query_types=["domain"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            tool="whois",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_whois",
            query_types=["domain", "ip"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            tool="crtsh",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_crtsh",
            query_types=["domain"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            tool="email_security",
            latency_class="fast",
            # A registry-published DNS record read directly: the highest
            # reliability a technical measurement gets short of a court order.
            reliability="A",
            label_key="search.tool_email_security",
            query_types=["domain"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            tool="dns_records",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_dns",
            query_types=["domain"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            tool="theharvester",
            reliability="D",
            label_key="search.tool_theharvester",
            query_types=["domain"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            tool="shodan_host",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_shodan_host",
            query_types=["ip", "domain"],
            default_query_type="ip",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="favicon_pivot",
            reliability="C",
            label_key="search.tool_favicon_pivot",
            query_types=["url"],
            default_query_type="url",
            requires_key=True,
        ),
        ToolDescriptor(
            # Structural hash of the page markup — the sibling of favicon_pivot.
            # Reliability B: a measurement we take ourselves, but the cluster
            # around it is Shodan's index, not our observation.
            tool="dom_hash_pivot",
            reliability="B",
            latency_class="fast",
            label_key="search.tool_dom_hash_pivot",
            query_types=["url", "domain"],
            default_query_type="url",
            description_key="search.tool_dom_hash_pivot_desc",
        ),
        ToolDescriptor(
            tool="dnstwist",
            reliability="D",
            label_key="search.tool_dnstwist",
            query_types=["domain"],
            default_query_type="domain",
        ),
        ToolDescriptor(
            # Historical resolutions — the infrastructure pivot axis. Keyless.
            tool="passive_dns",
            reliability="B",
            label_key="search.tool_passive_dns",
            query_types=["domain", "ip"],
            default_query_type="domain",
            description_key="search.tool_passive_dns_desc",
        ),
        ToolDescriptor(
            # BGP/registry context: who carries this address. Keyless.
            tool="asn_lookup",
            reliability="B",
            label_key="search.tool_asn_lookup",
            query_types=["ip", "asn"],
            default_query_type="ip",
            description_key="search.tool_asn_lookup_desc",
        ),
    ],
)

# origin_resolve is OFF by default: it probes candidate addresses DIRECTLY
# from the operator's server (including third-party hosts such as mail or
# shared-hosting servers) to find the origin behind a CDN. Enable it
# deliberately with ENABLE_ORIGIN_RESOLVE=true in .env.
ORIGIN_RESOLVE_ENABLED = os.getenv("ENABLE_ORIGIN_RESOLVE", "false").strip().lower() in ("1", "true", "yes")
if ORIGIN_RESOLVE_ENABLED:
    MANIFEST.tools.append(ToolDescriptor(
        # The real address behind a CDN. Keyless. Reliability B: candidates
        # come from third parties (crt.sh, passive DNS), but the ANSWER is a
        # two-gate measurement — direct probe with the domain's Host header
        # plus a negative control. Nothing unverified is emitted.
        tool="origin_resolve",
        reliability="B",
        label_key="search.tool_origin_resolve",
        query_types=["domain", "url"],
        default_query_type="domain",
        description_key="search.tool_origin_resolve_desc",
    ))


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    start = time.time()
    findings, edges, errors = [], [], []

    try:
        if req.tool == "subfinder":
            findings, edges, errors = await run_subfinder(req.query, req.job_id)
        elif req.tool == "whois":
            findings, edges, errors = await run_whois(req.query, req.query_type, req.job_id)
        elif req.tool == "crtsh":
            findings, edges, errors = await run_crtsh(req.query, req.job_id)
        elif req.tool == "dns_records":
            findings, edges, errors = await run_dns_records(req.query, req.job_id)
        elif req.tool == "email_security":
            findings, edges, errors = await run_email_security(
                req.query, req.query_type, req.job_id)
        elif req.tool == "theharvester":
            findings, edges, errors = await run_theharvester(req.query, req.job_id)
        elif req.tool == "shodan_host":
            findings, edges, errors = await run_shodan_host(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "favicon_pivot":
            findings, edges, errors = await run_favicon_pivot(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "passive_dns":
            findings, edges, errors = await run_passive_dns(
                req.query, req.query_type, req.job_id)
        elif req.tool == "origin_resolve":
            if not ORIGIN_RESOLVE_ENABLED:
                errors.append("origin_resolve is disabled (ENABLE_ORIGIN_RESOLVE=false).")
            else:
                findings, edges, errors = await run_origin_resolve(
                    req.query, req.query_type, req.job_id)
        elif req.tool == "asn_lookup":
            findings, edges, errors = await run_asn(
                req.query, req.query_type, req.job_id)
        elif req.tool == "dom_hash_pivot":
            findings, edges, errors = await run_dom_hash_pivot(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "dnstwist":
            findings, edges, errors = await run_dnstwist(req.query, req.query_type, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
