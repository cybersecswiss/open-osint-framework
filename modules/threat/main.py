import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.abuseipdb_runner import run_abuseipdb
from tools.greynoise_runner import run_greynoise
from tools.malwarebazaar_runner import run_malwarebazaar
from tools.threatfox_runner import run_threatfox
from tools.urlhaus_runner import run_urlhaus
from tools.urlscan_runner import run_urlscan
from tools.virustotal_runner import run_virustotal
from tools.ransomware_runner import run_ransomware
from tools.cve_runner import run_cve
from tools.c2intel_runner import run as run_c2intel
from tools.ioc_reputation_runner import run as run_ioc_reputation
from tools.otx_runner import run_otx
from tools.ransomware_intel_runner import run_ransomware_intel
from tools.ransomlook_runner import run_ransomlook_crypto, run_ransomlook_search

app = FastAPI(title="OSINT Module: Threat Intel", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="threat",
    label_key="search.module_threat",
    category="threat-intel",
    description_key="search.module_threat_desc",
    tools=[
        ToolDescriptor(
            tool="ransomware_group_intel",
            latency_class="medium",
            requires_key=True,
            # Published by the tracker from leak-site and negotiation data —
            # a well-sourced secondary account, not a primary record.
            reliability="B",
            label_key="search.tool_ransomware_intel",
            query_types=["keyword"],
            default_query_type="keyword",
        ),
        ToolDescriptor(
            tool="otx_pulses",
            latency_class="fast",
            requires_key=True,
            # A pulse is a community assertion by a named author, not a vendor
            # verdict — useful as a lead, rated as one.
            reliability="C",
            label_key="search.tool_otx",
            query_types=["ip", "domain", "url", "hash"],
            default_query_type="ip",
        ),
        ToolDescriptor(
            tool="virustotal",
            reliability="B",
            label_key="search.tool_virustotal",
            query_types=["domain", "ip", "url", "hash"],
            default_query_type="domain",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="abuseipdb",
            reliability="C",
            label_key="search.tool_abuseipdb",
            query_types=["ip"],
            default_query_type="ip",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="urlhaus",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_urlhaus",
            query_types=["domain", "url", "hash"],
            default_query_type="domain",
            # URLhaus works keyless; an Auth-Key only raises rate limits.
            # Advertising requires_key=True made the UI gate the tool
            # even though it runs fine without one.
            requires_key=False,
        ),
        ToolDescriptor(
            tool="greynoise",
            reliability="B",
            label_key="search.tool_greynoise",
            query_types=["ip"],
            default_query_type="ip",
        ),
        ToolDescriptor(
            tool="urlscan",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_urlscan",
            query_types=["domain", "url", "ip"],
            default_query_type="domain",
            # Keyless public-search lookup; requires_key stays false.
        ),
        ToolDescriptor(
            tool="threatfox",
            latency_class="fast",
            reliability="B",
            label_key="search.tool_threatfox",
            query_types=["domain", "ip", "url", "hash"],
            default_query_type="ip",
            requires_key=True,
        ),
        ToolDescriptor(
            tool="malwarebazaar",
            reliability="B",
            label_key="search.tool_malwarebazaar",
            query_types=["hash"],
            default_query_type="hash",
            requires_key=True,
        ),
        ToolDescriptor(
            # RansomLook: leak-site posts, RANSOM NOTES, markets and actor
            # aliases in one keyless call. Reliability B, same as
            # ransomware_watch and for the same reason — a curated aggregator
            # of primary leak-site material, not our own observation and not
            # a reputation opinion. Measured latency: ~1.5 s for a
            # broad term, so `fast` would be a lie and `slow` unfair.
            tool="ransomlook_search",
            reliability="B",
            latency_class="medium",
            label_key="search.tool_ransomlook_search",
            query_types=["keyword", "username"],
            default_query_type="keyword",
            description_key="search.tool_ransomlook_search_desc",
        ),
        ToolDescriptor(
            # Wallets attributed to a named group. Forward direction only —
            # there is no address→group endpoint upstream, and iterating ~200
            # groups per search would be abuse of a free service.
            tool="ransomlook_crypto",
            reliability="B",
            latency_class="fast",
            label_key="search.tool_ransomlook_crypto",
            query_types=["keyword"],
            default_query_type="keyword",
            description_key="search.tool_ransomlook_crypto_desc",
        ),
        ToolDescriptor(
            # Ransomware leak-site victims + group profiles. Keyless tier is
            # rate limited to 1 req/min; a free key removes that.
            tool="ransomware_watch",
            reliability="B",
            label_key="search.tool_ransomware_watch",
            query_types=["domain", "keyword"],
            default_query_type="keyword",
            description_key="search.tool_ransomware_watch_desc",
        ),
        ToolDescriptor(
            # Known C2 infrastructure from Censys scans (C2IntelFeeds).
            # Reliability B: an observation of the C2 software itself, not a
            # reputation opinion — but derived by a third party, not by us.
            tool="c2_intel",
            reliability="B",
            label_key="search.tool_c2_intel",
            query_types=["domain", "ip", "url"],
            default_query_type="domain",
            description_key="search.tool_c2_intel_desc",
        ),
        ToolDescriptor(
            # Agreement across independent open blocklists. Reliability C:
            # aggregated third-party reporting whose provenance varies by
            # feed — the value is the count of independent lists, not any
            # single one of them.
            tool="ioc_reputation",
            reliability="C",
            label_key="search.tool_ioc_reputation",
            query_types=["ip", "domain", "url", "hash"],
            default_query_type="ip",
            description_key="search.tool_ioc_reputation_desc",
        ),
        ToolDescriptor(
            # NVD detail + CISA KEV "exploited in the wild" flag. Keyless.
            tool="cve_lookup",
            reliability="A",
            label_key="search.tool_cve_lookup",
            query_types=["cve"],
            default_query_type="cve",
            description_key="search.tool_cve_lookup_desc",
        ),
    ],
)


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
        if req.tool == "virustotal":
            findings, edges, errors = await run_virustotal(req.query, req.query_type, req.options)
        elif req.tool == "ransomware_group_intel":
            findings, edges, errors = await run_ransomware_intel(
                req.query, req.query_type, req.job_id, req.options)
        elif req.tool == "otx_pulses":
            findings, edges, errors = await run_otx(
                req.query, req.query_type, req.job_id, req.options)
        elif req.tool == "abuseipdb":
            findings, edges, errors = await run_abuseipdb(req.query, req.options)
        elif req.tool == "urlhaus":
            findings, edges, errors = await run_urlhaus(req.query, req.query_type, req.options)
        elif req.tool == "greynoise":
            findings, edges, errors = await run_greynoise(req.query)
        elif req.tool == "urlscan":
            findings, edges, errors = await run_urlscan(req.query, req.query_type, req.options)
        elif req.tool == "threatfox":
            findings, edges, errors = await run_threatfox(req.query, req.query_type, req.options)
        elif req.tool == "malwarebazaar":
            findings, edges, errors = await run_malwarebazaar(req.query, req.query_type, req.options)
        elif req.tool == "ransomware_watch":
            findings, edges, errors = await run_ransomware(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "c2_intel":
            findings, edges, errors = await run_c2intel(
                req.query, req.options, req.job_id, req.query_type)
        elif req.tool == "ioc_reputation":
            findings, edges, errors = await run_ioc_reputation(
                req.query, req.options, req.job_id, req.query_type)
        elif req.tool == "cve_lookup":
            findings, edges, errors = await run_cve(
                req.query, req.query_type, req.job_id)
        elif req.tool == "ransomlook_search":
            findings, edges, errors = await run_ransomlook_search(
                req.query, req.query_type, req.options, req.job_id)
        elif req.tool == "ransomlook_crypto":
            findings, edges, errors = await run_ransomlook_crypto(
                req.query, req.query_type, req.options, req.job_id)
        else:
            errors.append(f"Unknown tool: {req.tool}")
    except Exception as e:  # noqa: BLE001 — return a clean error, never a 500
        errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
