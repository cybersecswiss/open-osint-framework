"""OSINT Module: Corporate & people (registers, ownership, sanctions).

Every other module in the framework starts from a technical selector — a
username, a domain, a hash, a wallet. This one starts from a **name**: a
company or a person. That is the entry point a procurement, sanctions-evasion
or shell-company case actually has, and until now the framework had nothing
for it beyond the key-gated `opensanctions` tool.

All five tools are keyless. Reliability is declared per source, not per
module, because they are genuinely different kinds of statement: an official
commercial-register publication (A) is not a community-maintained knowledge
base (C).
"""
import time

from fastapi import FastAPI

from schemas import ManifestResponse, RunRequest, RunResponse, ToolDescriptor, make_run_response
from tools.court_runner import run as run_court
from tools.finma_runner import run as run_finma
from tools.geo_runner import run as run_geo
from tools.gleif_runner import run as run_gleif
from tools.lobbywatch_runner import run as run_lobbywatch
from tools.sanctions_runner import run as run_sanctions
from tools.transport_runner import run_aircraft, run_vessel
from tools.shab_runner import run as run_shab
from tools.staatskalender_runner import run as run_staatskalender
from tools.telsearch_runner import run as run_telsearch
from tools.wikidata_runner import run as run_wikidata
from tools.zefix_runner import run as run_zefix

app = FastAPI(title="OSINT Module: Corporate & People", docs_url=None, redoc_url=None)


MANIFEST = ManifestResponse(
    name="corporate",
    label_key="search.module_corporate",
    category="corporate",
    description_key="search.module_corporate_desc",
    tools=[
        ToolDescriptor(
            # Official Swiss commercial-register publications: officers,
            # signing authority, seat, UID, deletions. A primary record.
            tool="shab_registry",
            reliability="A",
            label_key="search.tool_shab_registry",
            description_key="search.tool_shab_registry_desc",
            # btc/eth: OFAC designates wallet addresses on
            # the SDN list, and a sanctions hit on an address is the most
            # citable finding a crypto case can produce — an authority's own
            # publication rather than a vendor's risk opinion.
            query_types=["company_name", "person_name", "keyword",
                         "btc_address", "eth_address"],
            default_query_type="company_name",
        ),
        ToolDescriptor(
            # The commercial register's current STATE, where shab_registry
            # gives its published EVENTS. Adds the corporate network (branch
            # offices, takeovers, auditor), the purpose, the capital and the
            # previous names as structured fields.
            # latency_class deliberately NOT declared: a search costs one
            # POST plus up to ten detail GETs and has not been measured
            # against a live account, so it keeps the unmeasured default.
            tool="zefix_registry",
            reliability="A",
            requires_key=True,
            label_key="search.tool_zefix_registry",
            description_key="search.tool_zefix_registry_desc",
            query_types=["company_name", "company_id", "keyword"],
            default_query_type="company_name",
        ),
        ToolDescriptor(
            # The one Swiss source that makes a NEGATIVE statement about a
            # company: the supervisor's public list of parties acting without
            # the authorisation their business requires. A hit is not an
            # indication, it is a federal authority saying so in public —
            # hence A, and hence the entry page as the finding's url.
            # latency_class NOT declared: one search plus up to twelve detail
            # pages, measured at ~4 s, which is the honest `medium` default.
            tool="finma_warnlist",
            reliability="A",
            label_key="search.tool_finma_warnlist",
            description_key="search.tool_finma_warnlist_desc",
            # `domain` earns its place: 336 of the 2302 entries are filed
            # under a bare website, because the operation never had a company.
            query_types=["company_name", "person_name", "domain", "keyword"],
            default_query_type="company_name",
        ),
        ToolDescriptor(
            # Global LEI register: who owns whom, across jurisdictions.
            tool="gleif_lei",
            reliability="A",
            label_key="search.tool_gleif_lei",
            description_key="search.tool_gleif_lei_desc",
            query_types=["company_name", "keyword"],
            default_query_type="company_name",
        ),
        ToolDescriptor(
            # EU FSF + OFAC SDN, fetched from the issuing authority.
            tool="sanctions_screen",
            reliability="A",
            label_key="search.tool_sanctions_screen",
            description_key="search.tool_sanctions_screen_desc",
            query_types=["company_name", "person_name", "keyword"],
            default_query_type="company_name",
        ),
        ToolDescriptor(
            # 1540 vessels sit in the SDN file this module already
            # downloads. A ship keeps its IMO
            # number for life, across every change of name, flag and owner —
            # which is exactly why it is the selector a sanctions-evasion
            # case turns on, and why the framework not having one was the
            # central gap.
            tool="vessel_sanctions",
            reliability="A",
            label_key="search.tool_vessel_sanctions",
            description_key="search.tool_vessel_sanctions_desc",
            query_types=["vessel", "imo_number"],
            default_query_type="vessel",
        ),
        ToolDescriptor(
            # 342 aircraft, same file, same argument. For these the SDN
            # NAME is the registration.
            tool="aircraft_sanctions",
            reliability="A",
            label_key="search.tool_aircraft_sanctions",
            description_key="search.tool_aircraft_sanctions_desc",
            query_types=["aircraft"],
            default_query_type="aircraft",
        ),
        ToolDescriptor(
            # Community knowledge graph — leads, not records.
            tool="wikidata_entity",
            reliability="C",
            label_key="search.tool_wikidata_entity",
            description_key="search.tool_wikidata_entity_desc",
            query_types=["company_name", "person_name", "keyword"],
            default_query_type="company_name",
        ),
        ToolDescriptor(
            # All Swiss court decisions, federal and cantonal, full text.
            # The only source here that yields a signed document rather than
            # a record ABOUT someone — hence A, and hence the PDF as the
            # finding's url. Measured at ~0.4 s for a phrase query including
            # the negative control, so `fast`.
            tool="court_decisions",
            reliability="A",
            latency_class="fast",
            label_key="search.tool_court_decisions",
            description_key="search.tool_court_decisions_desc",
            # `domain` is deliberate: cybercrime judgments name the platform,
            # the shop or the phishing domain in the text far more often than
            # they name a natural person.
            query_types=["person_name", "company_name", "keyword", "domain"],
            default_query_type="person_name",
        ),
        ToolDescriptor(
            # Resolves the `location` nodes the rest of the framework already
            # produces (EXIF GPS, visual geolocation, Telegram geo, registered
            # seat) into an address, a building, a parcel and a canton.
            # Federal geodata, so A — but the reverse direction is an
            # inference and carries a lower per-finding confidence.
            tool="geo_ch",
            reliability="A",
            latency_class="fast",
            label_key="search.tool_geo_ch",
            description_key="search.tool_geo_ch_desc",
            # `tg_geo` is a lat,long pair, which this runner detects and
            # resolves in reverse — the same shape it accepts under `address`.
            query_types=["address", "tg_geo"],
            default_query_type="address",
        ),
        ToolDescriptor(
            # Who from federal politics is attached to this company — and who
            # they let into the Bundeshaus. The only source here that answers
            # a question about INFLUENCE rather than about a company's own
            # record, and the only one producing a person→person edge.
            #
            # Reliability B, not A: a well-sourced volunteer register with
            # per-entry provenance is strong, but it is a compilation about
            # third parties, not a primary record. Each finding carries the
            # entry's own `quelle_url` so a single tie can be upgraded by
            # opening the register extract it cites.
            tool="lobbywatch_ties",
            reliability="B",
            label_key="search.tool_lobbywatch_ties",
            description_key="search.tool_lobbywatch_ties_desc",
            query_types=["person_name", "company_name", "company_id"],
            default_query_type="person_name",
        ),
        ToolDescriptor(
            # The Federal Chancellery's own directory of who holds which
            # federal office. Reliability A for the same reason shab_registry
            # is A: the publishing authority's own record, not a compilation
            # about third parties. Answers "does this person actually hold
            # the office they claim", which no other tool here can.
            tool="staatskalender",
            reliability="A",
            latency_class="fast",
            label_key="search.tool_staatskalender",
            description_key="search.tool_staatskalender_desc",
            query_types=["person_name", "company_name", "phone", "email", "domain"],
            default_query_type="person_name",
        ),
        ToolDescriptor(
            # Swiss public directory: address and phone, both directions.
            tool="tel_search_ch",
            reliability="B",
            label_key="search.tool_tel_search_ch",
            description_key="search.tool_tel_search_ch_desc",
            query_types=["company_name", "person_name", "phone"],
            default_query_type="company_name",
        ),
    ],
)

_TOOLS = {
    "court_decisions": run_court,
    "geo_ch": run_geo,
    "shab_registry": run_shab,
    "zefix_registry": run_zefix,
    "finma_warnlist": run_finma,
    "gleif_lei": run_gleif,
    "sanctions_screen": run_sanctions,
    "vessel_sanctions": run_vessel,
    "aircraft_sanctions": run_aircraft,
    "wikidata_entity": run_wikidata,
    "lobbywatch_ties": run_lobbywatch,
    "staatskalender": run_staatskalender,
    "tel_search_ch": run_telsearch,
}


@app.get("/health")
async def health():
    return {"status": "ok", "module": MANIFEST.name}


@app.get("/manifest", response_model=ManifestResponse)
async def manifest():
    return MANIFEST


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    start = time.time()
    findings, edges, errors = [], [], []

    runner = _TOOLS.get(req.tool)
    if runner is None:
        errors.append(f"Unknown tool: {req.tool}")
    else:
        try:
            findings, edges, errors = await runner(
                req.query, req.options, req.job_id, req.query_type)
        except Exception as e:  # noqa: BLE001 — a clean error, never a 500
            errors.append(f"{req.tool} crashed: {type(e).__name__}: {e}")

    return make_run_response(req.job_id, req.tool, start, findings, edges, errors)
