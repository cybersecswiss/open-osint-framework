# OOF — Architecture

How the system is built and what runs where — for contributors and for
anyone who has to reason about where data goes. Installation and operation
are in [install.en.md](install.en.md) and [operations.en.md](operations.en.md).

Where it matters, this document records *why* something is the way it is —
usually the part worth knowing before changing it.

---

## 1. The product in one paragraph

A multi-tenant OSINT framework whose core promise is **data sovereignty**:
the operator supplies the search engine and the UI, but the investigation
data physically lives with the organisation using it — a separate Docker
stack (the *data server* or *agent*) with its own Postgres and, in operator
mode, its own Keycloak. The organisation is the data controller; the
framework operator processes searches, not stored case files. In the
all-in-one installation both stacks run on one host and talk over an
internal Docker network.

Three rules follow from that, and they show up everywhere in the code:

1. **The operator must not read case data.** Findings are pushed to the
   data server, not stored locally. The framework's own `entities`
   table exists only as a fallback path while a data server is unreachable.
2. **The operator must not manage the organisation's users.** In operator
   mode those accounts live in an IdP on the data server that the operator
   has no admin access to.
3. **An auth failure toward the agent is never "agent unavailable."**
   Treating it as such would silently divert case data into the
   operator's database — see `services/agent_client.py`.

---

## 2. Runtime landscape

Two Compose projects:

| Project | Containers | Role |
|---|---|---|
| `oof` | ~26 | framework (operator side) |
| `oof-agent` | 2 in all-in-one (`agent`, `postgres`), 4 on a separate data server (+ `keycloak`, `proxy`) | data server |

`nginx` is the only framework container that publishes ports (HTTP and
HTTPS, default 80/443); everything else is reachable only on the internal
Docker network. In all-in-one the agent joins that network as
`data-agent-local` and publishes nothing.

### 2.1 Framework containers

**Infrastructure**

| Container | Internal port | Purpose |
|---|---|---|
| `postgres` | 5432 | databases `osint`, `license`, `keycloak`, `n8n` |
| `redis` | 6379 | job state, scheduler mutex, AI job results |
| `keycloak` | 8080 | **two realms**: `osint` (tenants) and `platform` (product owners) |
| `nginx` | 80 / 443 | sole ingress, path-based routing |
| `n8n` | 5678 | editable AI prompt workflows (§8.2, §8.4) |
| `prometheus` / `grafana` | 9090 / 3000 | metrics, exposed under `/grafana/` |
| `updater` | 9999 | sidecar holding the Docker socket — see §8.6 |

**Application**

| Container | Purpose |
|---|---|
| `api` | FastAPI backend, 2 uvicorn workers |
| `frontend` | React 18 + Antd + Cytoscape |
| `license` | license server = the tenant registry, own DB and DB user |

**OSINT modules** — 13 containers on ports 8010–8150, plus `tor` (SOCKS
9050) as the egress path for darknet tooling. See §6. Plus `capture` (8160,
headless Chromium for evidence, own network — §8.5c).

### 2.2 Networks

Bridge networks `internal` and `external`, plus a dedicated `capture`
network (§8.5c). Effectively everything sits on `internal`; nginx bridges to
the outside. The `updater` is `internal`-only by design and is never routed
through nginx.

Every container carries a `json-file` logging cap of 10 MB × 3 files —
without it, a couple of dozen containers fill the disk silently.

---

## 3. Trust zones

```
┌─ ZONE 1: OPERATOR ─────────────────────────────────────┐
│  nginx → frontend / api → 14 modules → internet        │
│  framework DB: metadata ONLY (case no., title, jobs,   │
│  audit, monitoring, news). No entities.                │
│  Keycloak realm `osint`                                │
└──────────────┬─────────────────────────────────────────┘
               │  X-Framework-Key = PER TENANT
               │  (issued with the licence)
               ▼
┌─ ZONE 2: ORGANISATION (sovereign, own server) ─────────┐
│  Caddy (ACME) :443                                     │
│    ├─ agent    (FastAPI: /api/ingest, /api/cases/…)    │
│    └─ keycloak (org IdP — operator has NO admin)       │
│  postgres: cases, entities, edges, audit_log           │
└────────────────────────────────────────────────────────┘

┌─ ZONE 3: LICENSE SERVER (the bridge) ──────────────────┐
│  tenant → agent_url | agent_key | idp_url |            │
│           email_domains | enabled_modules | ai_enabled │
│  Reachable only with X-Internal-Key, never public.     │
└────────────────────────────────────────────────────────┘

┌─ ZONE 4: PRODUCT-OWNER CONSOLE /glbadmin ──────────────┐
│  Separate realm `platform`, separate login,            │
│  get_platform_admin() instead of get_current_user().   │
│  May manage tenants — may never see case data.         │
└────────────────────────────────────────────────────────┘
```

---

## 4. Where the data actually lives

**Framework DB `osint`** (operator): case *metadata* only (number, title,
members), search jobs, the audit log (HMAC chain, append-only trigger),
monitoring configurations and alerts, the news cache. Its `entities` and
`edges` tables are a fallback path that is used only while a data server is
unreachable; `scheduler.reconcile_local_fallback()` re-pushes those rows
every 30 minutes and deletes locally only what the data server accepted.

**Agent DB `agent`** (organisation): cases, entities, edges with
provenance (tool, URL, observed-at), the organisation's own audit and
activity log, evidence captures.

### 4.1 The framework→agent wire format

The payload must be at least as wide as **both** data models, or the
organisation's canonical store holds less than either side can represent:
the source URL, the observation time and the tool that asserted an *edge*
would die at the boundary. They are all carried.

| Field | Framework | Agent | On the wire |
|---|---|---|---|
| `entity.url` (from `Finding.url`) | yes | yes | yes |
| `entity.observed_at` (from `Finding.found_at`) | yes | yes | yes |
| `entity.found_at` | yes | yes | agent stamps ingest time — on purpose |
| `entity.notes` | yes | yes | yes — written from the node card via PATCH |
| `entity.corroborated_by` | yes | yes | yes — **merged**, not gap-filled |
| `entity.admiralty` | yes | yes | yes |
| `entity.last_verified` | yes | yes | yes |
| `entity.is_relevant` | yes | yes | set via PATCH, not ingest |
| `entity.is_primary` | yes | **no** | no — framework-only flag |
| `edge.source` | yes | yes | yes |
| `edge.corroborated_by` | yes | yes | yes — **merged**, not gap-filled |
| `edge.data` | yes | yes | yes |

**Two timestamps, on purpose.** `found_at` is when the agent stored the
row; `observed_at` is when the source said it. Keeping them apart means
older rows keep their original meaning instead of silently acquiring a new
one, and for fast-moving sources (leak sites, Telegram, pastes)
`observed_at` is the evidentiary one.

**One field accumulates rather than gap-fills.** `corroborated_by` is
merged as a sorted, deduplicated union on every push. Neither `DO NOTHING`
(loses the newcomer) nor overwrite (loses the history) would preserve "these
four tools have said this over time", which is the point of the column.

**Everything else is gap-fill, not overwrite.** The ingest upserts
`url`/`observed_at`/`edge.source` with `COALESCE(stored, incoming)`. A
plain `DO NOTHING` would leave every pre-existing row uncitable forever —
a re-scan could never fill columns added later. `COALESCE` in this
direction fills a NULL and never touches a stored value, so identity
fields (label, data, confidence) and investigator state (`is_relevant`,
`notes`) are safe, and the placeholder-freeze logic in the search flush
still holds. A re-scan of an existing case therefore *enriches* it.

### 4.2 Migration paths differ by side

* **Framework** — Alembic. `alembic upgrade head` runs in the api
  entrypoint. Baseline is `0001_baseline` (a deliberate no-op marking the
  pre-existing schema).
* **Agent** — no Alembic. `data-agent/app/bootstrap.py` holds an
  idempotent `ADHOC_MIGRATIONS` list of `ADD COLUMN IF NOT EXISTS`
  statements applied on every boot. This is the right shape for a data
  server the operator cannot administer, but it means **agent schema
  changes are expensive to ship one at a time** — batch them.

---

## 5. The investigation path

```
POST /api/v1/search                     routers/search.py
 ├─ _ensure_case_and_modules()          case ownership + licence + query_type
 ├─ create SearchJob (status=running)
 ├─ _expand_queries()                   facets: base + up to 5 variants
 └─ BackgroundTask _run_search()        ← asynchronous from here
      │
      │  variants run SEQUENTIALLY (rate limits)
      ▼
    run_modules()                       services/osint_orchestrator.py
      ├─ manifests (cached at startup) → plan of (module, tool, url)
      ├─ load_keys()                    Fernet-decrypted API keys from DB
      ├─ asyncio.gather over all tools, 300 s timeout each
      ├─ on_progress()   → SearchJob.tool_progress  (live table in the UI)
      └─ on_module_complete() → _flush(final=False) ← incremental persist
             │
             ▼
        build_graph()                   services/graph_builder.py
          ├─ TYPE_MAP canonicalisation + redundant prefix strip
          ├─ uuid5(_NS, case:type:label) → deterministic ids
          ├─ root node registered AFTER the findings pass
          └─ virtual endpoints for unresolved edge targets
             │
             ▼
        push_to_agent()                 services/agent_client.py
          X-Framework-Key = tenant_registry.get_agent_key(tenant)
             │
             ▼
        POST /api/ingest (agent)        data-agent/app/routers/ingest.py
          ON CONFLICT DO NOTHING; dangling edges skipped, not fatal
```

### 5.1 Invariants that are easy to break

* **Virtual placeholders are held back until the final flush.** They share
  the deterministic id of the real node they stand in for, and the agent
  ingests `ON CONFLICT DO NOTHING` — sending one early permanently freezes
  a confidence-0.5 shell in place of the real finding. The root node is
  explicitly **not** exempt from that hold-back; making it exempt makes a
  multi-module search lose its payload.
* **`keyword` and `btc_address` keep their original casing.** Runners emit
  edge endpoints verbatim (`from_entity=f"keyword:{query}"`), so
  lowercasing the root strands it with zero edges next to the real node —
  on every proper-noun search.
* **Auth errors are deliberately not caught** in `_flush`. They propagate,
  the job is marked failed, and nothing is written locally.
* **Facet variants run sequentially.** 5 variants × N tools in parallel
  reliably gets the sources to rate-limit us.

### 5.1b Merged nodes

`POST /cases/{id}/entities/merge` folds nodes into one on the agent
(`routers/merge.py`, one transaction): edges re-pointed, duplicate edges
collapsed with combined corroboration, self-loops dropped, notes/URL carried
over, the merged names kept in `data.aliases`. Because entity ids are
deterministic, the agent also records `entity_aliases(alias_id → target_id)`,
and **every ingest consults it**: a finding for a merged-away id is folded into
the survivor (its tool added to `corroborated_by`) and edges are remapped —
otherwise the next search would silently recreate the merged node. Operator
side, alerts and watches are moved to the survivor.

### 5.2 Two further write paths

* `POST /search/preview` — runs everything, persists nothing. Returns
  candidates with the same deterministic ids a real search would assign,
  so the UI can flag what already exists.
* `POST /cases/{id}/entities/commit` — persists a chosen subset. Entity
  ids are **recomputed server-side** from the committed (type, label)
  rather than trusted from the client, so a forged id cannot collide with
  an unrelated node.

Together these are the pivot flow: preview → select → commit. Chaining is
a human decision by design, which is the legally relevant property.

---

## 6. Module layer — 14 modules, about 85 tools

Every module is an independent FastAPI container exposing exactly three
endpoints: `GET /health`, `GET /manifest`, `POST /run`.

| Module | Port | Tools | Query types | Key-gated tools |
|---|---|---|---|---|
| `alias` | 8010 | 5 — sherlock, whatsmyname, user_scanner, linkook, handle_sweep | username, email | — |
| `leaks` | 8020 | 5 — holehe, hibp, intelx, ghunt, hudsonrock | email, domain, username, gaia | hibp, ghunt |
| `infra` | 8030 | 13 — subfinder, whois, crtsh, email_security, dns_records, theharvester, shodan_host, favicon_pivot, dom_hash_pivot, dnstwist, passive_dns, asn_lookup, origin_resolve (off by default) | domain, ip, url, asn | shodan_host, favicon_pivot |
| `threat` | 8050 | 15 — ransomware_group_intel, otx_pulses, virustotal, abuseipdb, urlhaus, greynoise, urlscan, threatfox, malwarebazaar, ransomlook_search, ransomlook_crypto, ransomware_watch, c2_intel, ioc_reputation, cve_lookup | keyword, ip, domain, url, hash, username, cve | 7 of 15 |
| `darknet` | 8060 | 4 — ahmia, paste_search, seizure_watch, onion_scrape (off by default) | keyword, username, email, btc_address, domain | — (via Tor) |
| `messenger` | 8070 | 10 — telegram_channel, tgstat, telegram_username_hunt, telegram_deeplink_search, telegram_global_search, telegram_message_search, discord_invite, discord_snowflake, discord_deep, phone_messenger | tg_channel, username, tg_search, keyword, tg_msg_search, discord_invite, discord_id, phone | discord_deep |
| `crypto` | 8080 | 5 — blockchain_btc, etherscan_eth, blockscout, address_risk, wallet_attribution | btc_address, eth_address | etherscan_eth, wallet_attribution |
| `telegram` | 8090 | 6 — authenticated Telethon scanner (telegram_scan, telegram_channel_info, telegram_deep_search, telegram_user_lookup, telegram_phone_lookup, telegram_geo) | tg_channel, tg_search, tg_user, username, phone, tg_geo | session |
| `compliance` | 8100 | 1 — opensanctions | keyword, btc_address, eth_address | opensanctions |
| `forums` | 8110 | 4 — crime_forum_hunt, linkbase_lookup, threat_actor_check, pgp_lookup | username, jabber_id, tox_id, session_id, keyword, pgp_fingerprint, email | — |
| `image` | 8120 | 3 — exif_gps, code_scan, visual_geolocate | image_url | visual_geolocate |
| `news` | 8140 | 1 — news_search | keyword | — |
| `dating` | 8130 | 1 — cupidcrawl (off by default: special-category data) | username | — |
| `corporate` | 8150 | 13 — shab_registry, zefix_registry, finma_warnlist, gleif_lei, sanctions_screen, vessel_sanctions, aircraft_sanctions, wikidata_entity, court_decisions, geo_ch, lobbywatch_ties, staatskalender, tel_search_ch | company_name, person_name, company_id, keyword, phone, email, address, domain, btc_address, eth_address, vessel, imo_number, aircraft | zefix_registry |

The authoritative list is each module's `MANIFEST` (in `modules/<name>/main.py`)
and the live `/manifest` endpoint — a table that must be edited alongside the
code drifts, so regenerate this one from the manifests rather than by hand.

Unused port in the module range: **8040**.

**Pivot sources** — `passive_dns` (which domains pointed at this IP, and when;
Mnemonic pDNS) and `asn_lookup` (who carries this address; RIPEstat). Every
other infra tool answers "what is true now", which is precisely the state an
adversary changes once they are burned. `ransomware_watch` (ransomware.live)
on the keyless tier is limited to one request per minute per endpoint — a free
key removes that and the runner picks it up automatically. `cve_lookup`
combines NVD with CISA KEV (exploited-in-the-wild status).

**Name-first sources** — the `corporate` module. Every other module keys off a
technical selector; a procurement or sanctions-evasion case starts from a
company or a person. Most of it is keyless:

| Tool | Answers | Source |
|---|---|---|
| `shab_registry` | officers, signing authority, UID, seat, deletion | SHAB / FOSC (CH) |
| `gleif_lei` | who owns whom, across jurisdictions and scripts | GLEIF LEI |
| `sanctions_screen` | EU FSF + OFAC SDN, straight from the issuer | EU / US Treasury |
| `wikidata_entity` | holdings, officers, owners | Wikidata |
| `tel_search_ch` | public Swiss address and phone entries | tel.search.ch |

Two traps this module documents: SHAB accepts `query`/`q`/`fullText` and
**silently ignores all of them** (answering with all publications), and the
company's own address sits inside `commonsActual/company` — the document's
first `<street>` belongs to the *publishing authority*, so an unscoped read
gives every company the publisher's address.

**Vessels and aircraft.** A sanctions-evasion case very often turns on
neither a technical artefact nor a legal person but on a **ship**. Cargo
moves, ownership is layered through shells, and the vessel is the one thing
that cannot be re-registered out of existence — it keeps its IMO number for
life, across every change of name, flag and owner.

This needs **no new source and no new key**: the OFAC SDN list that
`sanctions_runner` already downloads contains vessels and aircraft, with
`SDN_Type` naming them outright, vessel-specific columns (call sign, type,
tonnage, GRT, flag, owner) and the IMO number in the remarks. For aircraft
the SDN *name* is the registration, with model, operator and serial numbers
in the remarks. Both tools rate Admiralty **A**: the statement comes from the
issuing authority and can be cited as "OFAC SDN, programme …, retrieved
<date>". The indexes are built in the same pass as the crypto-address index.

Four node types, and the split matters: `vessel`/`aircraft` are the assets,
`imo_number`/`aircraft_serial` are the identifiers that **outlive a
rename**. `build_graph` keeps the first finding per key and does not merge
`data`, so a ship modelled as a field on its owning organisation would
vanish the moment another registry reported that owner first. The registered
owner and the aircraft operator are emitted as `organization`, which is
what threads them straight into the existing company graph.

Two traps this pair documents:

* **The IMO check digit is not a nicety.** A mistyped IMO answers "not
  designated", which looks exactly like a clean result — the single worst
  thing a sanctions check can get wrong. A query that fails the check is
  refused instead of screened.
* **`from tools.sanctions_runner import _vessel_index` would be silently
  dead.** `_parse_ofac` *reassigns* the index dicts when it builds them, so
  the imported name would bind the empty dict that existed at import time
  and every lookup would return "not on the list", forever, with no error
  anywhere. The lookup goes through the module.

These are **not** a tracking capability. Live position needs a paid feed and
belongs in a key-gated tool alongside `wallet_attribution`. They answer one
question completely: is this ship or this aircraft designated, and what does
the designating authority say about it.

### 6.1 The manifest contract

The single best design decision in the project. A module's `MANIFEST`
declares its tools and the `query_types` each accepts. The backend polls
every `/manifest` once at startup and caches it; the orchestrator expands
`(module, query_type)` into a tool plan from that cache.

Adding a tool is therefore: one `ToolDescriptor` entry plus a runner. No
orchestrator change, no frontend change, no i18n change beyond the label
keys the manifest declares.

`modules/base/schemas.py` is **copied into each build context** by the
module Dockerfiles — deliberately not shared via a volume mount, so a
module can be shipped independently. The same holds for `safe_fetch.py`
and `handle_variants.py`; `scripts/check-shared-copies.sh` (run in CI) fails
when any copy drifts from its source. `credential(options, name)` resolves
API keys: request-supplied credentials win, the module's own `.env` is the
fallback.

### 6.2 Evaluability: rating, corroboration, ranking

Collecting is not the bottleneck — the tools return several hundred nodes
for one domain search. Deciding which twenty matter is. Three mechanisms,
all of which live in code rather than in a model:

**Admiralty rating.** A single float confidence was never comparable across
tools: 0.8 from Sherlock is an HTTP 200 on a profile page, 0.8 from HIBP
is a hit in a verified breach. The scale splits the two questions an analyst
actually asks —

* *Source reliability* (A–F) is declared **per tool in the manifest**, because
  only the module author knows what kind of statement its tool makes.
  A tool that declares nothing rates **F (cannot be judged)** — an honest
  gap, not a middling guess.
* *Information credibility* (1–6) is derived **per finding by the framework**,
  because only it can see whether other tools agreed. `1` is assigned solely
  when two or more independent tools reported the same thing. `5`
  ("improbable") is never assigned — nothing in the pipeline can justify it.

Rendered together as e.g. `B2`. The letter is the **best** reliability among
the reporting tools: if a registry and a scraper both return a value, the
registry's word is what it is worth, and a weak second source can only raise
credibility, never lower reliability.

**Corroboration.** `corroborated_by` lists every tool that independently
reported the same entity or relation. Without it, dedup lets the first
finding win and `ON CONFLICT DO NOTHING` discards the rest, throwing away
the strongest signal the system produces. It is keyed on the
deterministic entity id rather than the raw label, so two spellings of one
address still count as agreement, and it **accumulates across searches** — a
tool confirming a node months later is exactly the signal worth keeping (see
`_merge_arrays` in both `routers/search.py` and the agent's `ingest.py`).

**Where it surfaces.** The rating and the corroborating tool list travel
with every entity in `GET /cases/{id}/graph` and `/entities`, and the proxy
attaches a computed `relevance_score` to each. The UI shows the rating as a
chip on the node card and in the findings list, rings corroborated nodes in
the graph (a double ring — node size follows degree, which makes the loudest
source lead, so the ring is the counterweight), and orders the findings list
by the same score the PDF uses. Two implementations of a ranking would be two
rankings, so the browser never computes it.

**Relevance ranking** (`services/relevance.py`) — computed, never stored.
Four signals: corroboration (0.40), source reliability (0.25), degree
centrality (0.20), hops from the searched selector (0.15). Deliberately a
function of the case as it stands: mark a false positive or run another tool
and the ranking must change immediately; a stored column would be stale the
moment anything else moved, and nobody would know which rows were fresh.

### 6.3 Verification

Account discovery by URL is the noisiest thing the framework does — a hit is
an HTTP 200, and plenty of sites return 200 for any path. `modules/base/
verifier.py` is the shared two-gate check:

1. **Direct probe** — 200, the username still present in the *final* URL
   after redirects, and no known "not found" phrase in the body.
2. **Negative control** — the same URL template with a random, near-certainly
   unregistered username. The candidate must be *distinguishable* from it.
   A site that 200s identically for both is a catch-all, and the candidate is
   dropped.

Used by `sherlock`, `whatsmyname`, `user_scanner` and `linkook`.
`verify_accounts()` wraps it for runners that emit more than one
kind of finding: it verifies only the account findings, leaves the rest alone,
and **repairs the edges** — a runner that drops findings without dropping the
edges that pointed at them turns each false positive into a hollow placeholder
node instead of removing it.

Filtering false positives is reported through `NOTE_PREFIX`, so it never marks
a run as partial. A working filter is not a failure.

### 6.4 Runner conventions

* Edge endpoints use `entity_type:label` — this is mandatory. Breaking it
  strands nodes.
* `NOTE_PREFIX` (`"[note] "`) in the `errors` list marks informational
  notices (result caps, filtered false positives). `make_run_response()`
  moves them to `notes` and they never flip status to partial/error.
* Status is derived, not set: `success` (no real errors), `partial` (real
  errors plus findings), `error` (real errors, nothing found).
* A failing module is one entry in the result list, never an aborted
  search.

---

## 7. Authentication

`backend/app/auth.py` picks the JWKS to verify against from the token's
`iss` claim:

1. **Framework Keycloak** — matched against an explicit allow-list of four
   issuer strings. Deliberately not a prefix match: otherwise
   `http://keycloak:8080/realms/EVIL` would count as a framework token.
2. **Platform realm** — matched by the `/realms/<platform_realm>` suffix,
   because Keycloak emits different scheme/host issuers for the same realm
   depending on the inbound network. Safe, because the token is still
   verified against the framework's own platform realm JWKS.
3. **Data-server IdP** — `idp_url` looked up in the license server. If the
   token's `iss` does not match it, the request is rejected with
   "JWT issuer mismatch" — this is what stops a tenant-A token from being
   replayed against tenant-B endpoints.

Further properties:

* **The tenant comes from the `groups` claim**, never from a header. Any
  group whose normalised name is not `admin`/`investigator`/`reader`/
  `platform_admin` is a tenant. Multiple tenant groups are sorted so the
  result is at least deterministic, and a warning is logged.
* `alg` is taken from the JWKS entry, not from the attacker-controlled
  token header; `alg: none` is rejected outright.
* `aud` is not verified (Keycloak puts `account` there for SPA tokens);
  `azp` can be pinned via `ALLOWED_AZP`.
* JWKS cache TTL: 5 minutes, keyed by issuer.
* `get_platform_admin()` requires both a platform-realm issuer **and** the
  `platform_admin` role. A tenant token carrying that role is still
  rejected.

**Case visibility (need-to-know).** Within a tenant,
`services/case_access.py` is the single rule: a case with `restricted = true`
is visible to its creator, assignee, `members` and the tenant's admins, and to
nobody else — **404, not 403**, so its existence is not confirmed. Every route
touching a case asks it, including the indirect ones: search jobs, watches,
alerts, the AI path, and every endpoint that takes only an entity or edge id.
Those require `case_id`, and the agent scopes the write to that case
(`?case_id=` on PATCH/DELETE, `case_id` in the bulk delete), so a visible case
cannot be used as a door into a restricted one. Only the creator or an admin
may change `restricted`/`members`; each change is written to the
organisation's activity log (`case.access_change`).

**Login flow:** enter email → `GET /api/v1/resolve-tenant` maps the email
domain to a tenant and returns its OIDC config → the browser is redirected
to the right Keycloak.

---

## 8. Subsystems

### 8.1 Report

A plugin registry. Each file in `services/report/sections/` registers
itself with `@register_section(name=…, order=…, default=…)`, carries its
own Jinja2 template, and returns a `SectionData`. The generator renders
each fragment separately and stitches them into `base.html`, then hands
the result to WeasyPrint inside `asyncio.to_thread` (it is synchronous and
CPU-heavy).

Sections in render order: `cover` (0), `summary` (10), `key_findings`
(15), `entities_table` (20), `relationships` (25), `graph_snapshot` (28),
`searches` (30), `activity` (32), `alerts` (40), `timeline` (50), `evidence`
(60), `captures` (62). Four languages (de/en/fr/it) via `SectionStrings`.

`key_findings` opens the report with the twenty highest-ranked findings and
the reason each ranks where it does — which tools confirmed it and how the
source rates. Within `entities_table` the rows are ordered by the same
ranking rather than alphabetically: a few hundred `domain` rows sorted by
name bury whatever matters.

Entities and edges come from the agent in one shot, with a local-DB
fallback — except on an auth error, which is re-raised: a report is
evidentiary output and must not quietly change its source. **Alerts are
read from the framework DB unconditionally**, because monitoring is
operator-side and the agent's `/alerts` endpoint is an intentional stub.

Two rules the sections share, both in `report/filters.py` so no two
sections can disagree about what the case contains:

* **Placeholders are not findings.** `data.virtual` nodes exist to keep
  the graph connected; nobody asserted them. They are excluded from the
  tables and counted separately.
* **Relevance drives the selection.** If anything in the case is marked
  `is_relevant = true`, the report shows exactly that; otherwise it shows
  everything not marked as a false positive. Either way the report states
  which rule applied and how much it suppressed — a filtered report that
  doesn't say it is filtered is worse than an unfiltered one.

In the graph picture a **double ring** marks a finding two or more
independent tools reported. Node size follows degree, which makes the
loudest source lead visually; the ring is the counterweight, marking the
best-supported node rather than the most connected one.

The picture is deterministic inline SVG generated in
`report/graph_svg.py` — a radial layout by BFS depth from the most
connected node, capped at 70 nodes with the omitted count printed. No
headless browser: WeasyPrint renders SVG directly, and shipping a browser
into the API image for this would be a large dependency and a new failure
mode.

### 8.1b Export and playbooks

**Export** (`services/export.py`, `GET /cases/{id}/export?format=…`) — CSV,
Maltego CSV, MISP event, STIX 2.1 bundle. Two rules run through all four:
placeholders never leave the building, and provenance travels (source tool,
corroborating tools, Admiralty rating, source URL). Every export is audited
with a SHA-256 of the payload — handing findings to another organisation is
exactly the kind of act a case file must be able to prove.

Two deliberate choices worth knowing: MISP attributes go out with
`to_ids=false` unless the analyst marked the finding relevant (unvetted OSINT
must not arrive pre-armed for detection), and the STIX bundle carries a `note`
object declaring how many findings fall outside standard STIX vocabulary and
ship as `x-osint-entity`.

The **search root is not a placeholder.** It is virtual, but it is the
selector under investigation and it anchors most edges; treating it as an
unconfirmed endpoint would drop most of the exported relations.
`graph_builder` marks it `data.root = true`, and the ingest merges that one
key on conflict so a re-scan repairs cases written before the flag existed.

**Playbooks** (`services/playbooks.py`, `GET /search/playbooks`) — module
presets per offence type (ransomware, phishing, darknet trade, fraud/fake
shop, crypto fraud, sextortion, infrastructure). Configuration only, no new
collection path. Server-filtered to what the tenant can actually run, and each
entry says whether it fits the selector currently typed, so the form never
offers a preset that would 403 on submit.

**Delta** (`GET /cases/{id}/delta`) — what the last run added, bounded by the
job's `started_at` against the agent's `found_at`. Re-confirmed rows are not
reported as new. Removals are **not** tracked and the response says so: a
failed tool and a takedown are indistinguishable here, and reporting the
second when it was the first would be worse than silence.

### 8.1c Frontend delivery

Two properties of the SPA that decide how it feels rather than what it does.

**Route-level code splitting** (`src/router.tsx`). Every page is a
`React.lazy` chunk behind a `<Suspense>` boundary inside each layout, and
`vite.config.ts` pins React, AntD, Cytoscape and Leaflet into their own vendor
chunks. The first load therefore carries roughly half of what a single bundle
would — Cytoscape, the case view, the handbook, Leaflet and the whole
Product-Owner console arrive only when opened. The vendor split is the second
half: a routine deploy does not invalidate React and AntD, so a one-line label
fix does not cost every workstation a full re-download.

Both layouts are imported eagerly on purpose — they are the first screen, and
lazy-loading them trades the problem for a blank flash. `React.lazy` was
chosen over React Router's own per-route `lazy` because the latter delays the
*navigation* while the chunk downloads: the user clicks and nothing happens.

**Theme** (`App.tsx`). `light` / `dark` / `system`, default `system`, stored
in `localStorage`. Surfaces come from AntD's algorithm; the layouts read
`theme.useToken()` rather than hardcoded colours, and `<body>` is painted
explicitly so a dark UI does not sit on a white page during scroll overshoot.

**Accessibility.** A skip link (WCAG 2.1 SC 2.4.1), `<html lang>` kept in
sync with the UI language (otherwise a screen reader pronounces a German case
file with English phonemes), `prefers-reduced-motion` honoured, and every
interactive control carrying an accessible, **translated** name — a screen
reader announcing English names inside a German case file is the same defect
as a hardcoded `lang="en"`. When checking for unnamed controls, note that AntD
associates a `<Form.Item label=…>` with its control and that a checkbox's
children *are* its label.

**The graph canvas.** Cytoscape draws into a `<canvas>`: invisible to a screen
reader, unreachable by keyboard. It therefore has `role="application"` with a
name and description, a visible focus ring, and keyboard control (arrows pan,
`+`/`-` zoom, `0` fits). Deliberately **not** a node-by-node focus walk —
600 nodes make a tab order worse than none, and the equivalent *content* is
the findings table, not the picture. That table is **announced as the
alternative**, with a button that switches to it; an unannounced equivalent
satisfies neither SC 1.1.1 nor the person who needs it.

**Keyboard** (`components/layout/KeyboardShortcuts.tsx`). `g` then a letter
navigates; `?` lists them. Nothing fires while focus is in a field or inside
an AntD select/picker/modal — the guard that separates a shortcut layer from
a trap.

### 8.2 Monitoring

`MonitoringConfig` rows live operator-side. The backend scheduler
(`services/scheduler.py`, `monitoring_rescan_loop`) picks up due configs and
runs a search per config; `services/alerting.py` `raise_alerts_for_job()`
then writes the `Alert` rows. The follow-up **awaits** the search rather than
running beside it — the comparison is against `job.started_at`, so a parallel
task would almost always see an empty delta.

* `GET /entities/{id}/diff` is honestly named: the framework takes no entity
  snapshots, so it returns a **provenance history** (when the row was first
  stored, which tools have asserted it since, which alerts reference it)
  rather than an invented before/after.
* `services/notify.py` delivers by SMTP and webhook, configured **by the
  organisation** in `/admin → Alerting` with a test button per channel.

Three properties worth keeping:

* **The first run of a monitor does not alert.** It records what is already
  there (`monitoring_configs.baseline_at`). Otherwise one run on a fresh
  monitor produces an alert per existing finding — the search result wearing
  a different hat. An inbox that receives that once ignores the next one.
* **`partial` is an alertable outcome.** It is the *normal* one for
  multi-tool searches, and requiring `completed` would switch alerting off
  with no error anywhere. `failed` and `cancelled` raise nothing and take no
  baseline: nothing was stored, so the absence of findings proves nothing.
* **The mail carries no findings.** Counts, change types and a deep link.
  A mail server is outside the sovereign boundary, and this is the one
  place the framework would otherwise put case content into it. The webhook
  carries identifiers and change types, signed with HMAC-SHA256 over
  `"<timestamp>.<body>"` so a captured POST cannot be replayed.

Trigger types that this pipeline cannot produce are reported as unavailable
with a reason by `GET /monitoring/triggers`, rather than silently doing
nothing.

Three workflow JSONs sit in `n8n/workflows/` (`ai-link`, `ai-link-local`,
`ai-news`), and they are there for one reason: their prompts are meant to be
edited without a rebuild. Rescans, alerting and licence-expiry notices are
backend loops, for the same three reasons each time: they have to work on a
fresh install with no workflow import, they must not need a second
authentication path, and the audit entry needs an honest actor. The rule:
a workflow belongs in n8n only when a human is meant to edit it
(`n8n/workflows/README.md`).

⚠️ `import:workflow` **deactivates** what it imports (the bundled JSON files
carry `active: false`), so `entrypoint.sh` re-activates the two AI workflows
on every start. Without those two lines the AI function is dead after each
restart and the only symptom is a button that returns nothing.

### 8.3 News / Lagebild

An RSS harvester with a persistent cache in the framework DB
(`news_articles` plus per-feed poll state), a default set of DE/CH feeds,
full-text search over the DB, optional Gemini analysis, and its own
`/lagebild` page. Feeds are operator-maintained and passed to `module-news`
in the run options; the module falls back to its bundled defaults when the
list is empty.

### 8.4 AI linking

Licensed per tenant (`ai_enabled`), opt-in, button-triggered, never
automatic. The case graph is fetched, **credentials are scrubbed** (the
`_SENSITIVE` substring list covers password, cookie, token, credential,
hash, banner, …), per-entity `data` is bounded, and only structure plus
labels are handed to the editable n8n `ai-link` workflow.

It returns **suggestions only** — nothing is persisted. The analyst
commits chosen items through the normal pivot commit path. With the Gemini
provider, case data leaves the sovereign boundary; that is precisely why
the feature is licensed and consented, and why a local model is the
sovereign alternative.

### 8.4b What the operator holds — measured

`GET /api/v1/platform/tenants/{tenant}/data-exposure` walks the
operator-side tables and reports, per column, whether it is **metadata**
(exists so the framework can run), **case-linked** (identifies a case or an
entity without describing it) or **content** (describes what was found or
what was searched for).

Generated from the live schema on purpose. A paragraph saying what a
processor stores drifts the moment somebody adds a column; a measurement
cannot. It is the answer a data-processing agreement needs, and a column
added without a classification is reported as `unclassified` — which is the
useful failure rather than silent drift.

The content columns are few, and each has a reason:

| Held operator-side | Why it is there |
|---|---|
| `cases.title`, `cases.description` | written by the investigator; the operator has to show a case list |
| `search_jobs.query` | the selector. The search **runs** operator-side — this is irreducible |
| `monitoring_configs.query` | the same selector, re-run unattended. Also irreducible while the scheduler is operator-side |
| `entities.*`, `edges.*` | the fallback path only, and self-clearing via `reconcile_local_fallback()` |

**Alerts are not on that list.** They carry identifiers and categories, not
the finding itself or where it was found; the list resolves labels from the
agent at read time via `POST /api/entities/lookup`, exactly as the graph and
the report resolve everything else.

That lookup endpoint exists because the obvious implementation does not
scale: fetching `GET /cases/{id}/graph` to name three rows can push the api
container past its memory limit on a large case. It asks for the ids on the
page, in one request, and returns id, type, label, url and rating — nothing
else, so it cannot become a back door around `GET /cases/{id}/entities`.

**An open design question:** monitoring configs and alerts live
operator-side because the scheduler does. Moving them into the sovereign
store would mean the agent triggers searches, which means the data server
needs outbound access to the framework — a larger change than it looks, and
one that does not remove the selector from the operator's memory at run
time.

### 8.5 Audit

HMAC-chained entries with an append-only Postgres trigger and external
anchors in a dedicated volume. **`AUDIT_SELECTOR_MODE` defaults to
`hashed`**: only an HMAC fingerprint of the selector is stored, so two
identical searches stay correlatable while the operator cannot read what was
searched for. It fits the processor role; `full` is a development
convenience.

The redaction happens **before** the chain hash, so switching modes does
not invalidate anything already written — the chain and its external anchors
verify before and after a switch.

### 8.5b The organisation's activity log

The operator-side audit above answers "what did the operator's system do",
with the selector as a fingerprint. It cannot answer the question the **data
controller** gets asked — *who looked this person up, and why?*

`services/activity.record_activity()` therefore writes to the agent's
`POST /api/activity` **before** a search runs (`search.run`), when a watch is
created (`monitoring.create`) and on every unattended rescan
(`monitoring.rescan`, actor `scheduler`). Those entries carry the selector in
clear text and the stated **purpose / legal basis** — both belong to the
organisation. The operator's audit records only `purpose_given: true|false`.

* Entries are SHA-256 hash-chained on the agent (`GET /api/activity/verify`).
  No key: this makes an edit visible, it does not stop the organisation's
  own DBA.
* A tenant can make the purpose mandatory (`licenses.require_search_purpose`,
  set by the tenant admin). Then an unwritable record **blocks** the search
  (503 `activity_log_unavailable`) — the record is the point of the rule.
  Without the requirement, the search proceeds and the gap is logged.
* Read back per case via `GET /cases/{id}/activity` (UI tab "Search log").
  No local fallback: the operator holds no such record, and an empty list
  would read as "nobody searched".

### 8.5c Evidence capture

`capture` (port 8160) is a headless Chromium behind FastAPI. `POST /capture`
returns a full-page PNG, an MHTML archive (page + images + styles; rendered
HTML if the archive exceeds 25 MB), the SHA-256 of each, the final URL, the
redirect chain, status, time, UA and whether Tor was used. It stores nothing.
The api forwards the record to the agent (`POST /api/evidence`), which
**re-hashes on arrival** and keeps it as `bytea` in its own database — so
evidence is in the data server's backups and goes with a case delete. The
operator's audit keeps the two hashes; the organisation's activity log keeps
URL, hashes and actor.

The browser loads investigator-supplied URLs from inside the operator's
network, so it is fenced twice:

1. **Own Docker network `capture`** with only `api` and `tor`. From the
   container, `postgres`, `license`, `keycloak`, `updater` and `redis` do
   not even resolve.
2. **Every request checked** (`safe_fetch.assert_public_url`), including every
   redirect hop. Chromium follows a 3xx handed to it via `route.fulfill()`
   inside its network stack **without calling the route handler again** — so
   redirects are followed in Python (`_follow`) and the browser only ever
   sees final responses. The main document's chain is resolved before
   `goto()` so relative links resolve against the real page.

`.onion` goes through Tor (browser and `route.fetch` both proxied). Onion
pages take 5–70 s, hence the dedicated nginx location with a 130 s timeout.

### 8.6 Updater sidecar

The only container with the Docker socket. It exposes exactly one
internal, key-gated endpoint (`POST /update`) hardcoded to the `n8n`
service. Even a fully compromised API can trigger nothing worse than
"update n8n."

### 8.7 Scheduler

In-process background loops in `services/scheduler.py`, started with the
api: case auto-delete, monitoring rescans, news harvesting, audit anchoring,
forum-index refresh, licence-expiry notices, stale-job reaping and the
re-push of the local fallback. Each uses a Redis `SET NX EX` lock so the two
uvicorn workers cannot both fire the same run. Deliberately not n8n, so all
of this works on a fresh install without importing a workflow.

---

## 9. Data-server delivery

Procedures: [operations.en.md](operations.en.md#organisations-operator-mode) and [customer-server.en.md](customer-server.en.md). The structural facts:

**A release is a frozen set of files plus a manifest.** `scripts/release.sh`
builds the agent image, renders the data-server compose with that image
reference, copies the scripts and templates and writes `version.json`
carrying the version, the commit, the exact image reference and a **SHA-256
for every file the data server downloads** — all into `data-agent/dist/`
(gitignored), which nginx serves read-only at `/agent/`. Because it is a
copy, editing a script in the repository does not change what data servers
fetch until the next release.

**Two delivery modes**, and the manifest says which one a release used
(`delivery`), so `update.sh` needs no flag:

* **tarball (default)** — `docker save | gzip` next to the other artefacts,
  checksummed in the manifest; the data server `curl`s it and `docker load`s
  it. ~150 MB per update instead of only the changed layers, in exchange
  for needing **no registry, no second set of credentials and no DNS
  record**.
* **registry** — `scripts/release.sh <registry>`; push and pull.
  Better for frequent updates.

`docker load` adds an image rather than replacing one, so the previous
image stays on disk under its own tag — which is what makes `update.sh`'s
rollback more than a hope.

The manifest is what makes an update verifiable rather than hopeful. A plain
`docker compose pull` has three silent holes: a changed compose file never
arrives, the organisation cannot tell whether it is current, and a broken
image starts with nothing to roll back to. `install.sh` and `update.sh`
therefore both refuse on a checksum mismatch, and `update.sh` backs up first
and rolls back on a failed health check.

**The organisation sees when to update.** The agent's `/health` reports
`version` (from `--build-arg AGENT_VERSION`), `api_level` and
`capabilities`; `GET /admin/update-status` compares that with the published
manifest and the admin screen shows the release notes (`changes`, per
language) and the `update.sh` command. The same capability list drives the
self-test's "data store version" line (`services/selftest.py`).

**Two license routes are public, and only two.** The license server is
otherwise unreachable from outside. `location = /api/v1/license/validate`
and `= /api/v1/license/agent-key` are exact-path proxies with their own
rate-limit zone; both authenticate on `X-License-Key` and return only that
tenant's data. Without them `data-agent/install.sh` cannot complete.

### 9.1 The install flow

On the data server, `install.sh` (from `/agent/`) runs as root:

```
ask for framework URL + licence key + public address + TLS mode (letsencrypt|internal)
  → /api/v1/license/validate       resolve the tenant
  → /api/v1/license/agent-key      fetch the per-tenant key
  → generate secrets (Postgres, KC admin, backend client secret)
  → render Compose + Caddyfile + Keycloak realm from templates
  → bring up: postgres + agent + keycloak + Caddy (:80/:443)
```

The agent and the data server's Keycloak bind to `127.0.0.1` only;
everything public goes through Caddy with automatic Let's Encrypt. The
license server **rejects public `http://` URLs** when registering an agent
(internal Docker names stay allowed for all-in-one and test setups).

Nothing is matched up by hand: the per-tenant key comes from the licence,
and the operator only registers the https URLs.

---

## 10. Repository

```
setup.sh                 guided installation (allinone | operator)
docker-compose.yml       framework: infra + api + frontend + 14 modules + license
backend/                 FastAPI, Alembic migrations, tests
frontend/                React SPA (+ public/wiki: the in-app handbook)
modules/                 13 OSINT modules + base/schemas.py (the module contract)
data-agent/              data server: app, data-server compose, install/update/backup
license-server/          tenant registry
keycloak/                realm export for realm `osint`
nginx/ n8n/ monitoring/ tor/ capture/ updater/
scripts/                 configure-*, release, backup/restore, health, rebuild
docs/                    install, operations, data server, this file
```
