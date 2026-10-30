# OOF — Open OSINT Framework

**Self-hosted OSINT investigation platform with data sovereignty built in.**

[Deutsch](README.de.md) · [Installation](docs/install.en.md) · [Operations](docs/operations.en.md) · [Architecture](docs/architecture.md) · [Security](SECURITY.md)

**OOF** (Open OSINT Framework) bundles ~85 open-source-intelligence tools behind one web
interface: you enter a selector (email, username, domain, IP, phone
number, wallet, company, …), OOF runs the matching tools in parallel,
and the findings land in a case as an interactive graph — with source,
time and reliability rating for every single fact. Cases can be monitored
for changes, exported (PDF/DOCX report, CSV, Maltego, MISP, STIX) and
shared within the organisation.

The design rule behind everything: **whoever runs the search engine does
not get to hold the case data.** Investigation data lives on a *data
server* that belongs to the organisation using it — its own database, its
own user directory. On a single server (all-in-one) both simply run side
by side.

---

## Features

| Area | What you get |
|---|---|
| **Search** | 14 modules, ~85 tools (three sensitive ones off by default): usernames (Sherlock, WhatsMyName, …), email & breaches (Holehe, HIBP, Hudson Rock, GHunt), infrastructure (DNS, crt.sh, Shodan, passive DNS, subfinder, theHarvester), threat intel (VirusTotal, abuse.ch, OTX, GreyNoise, ransomware trackers), crypto (Etherscan, Blockscout, GoPlus), darknet over Tor (onion search, page reading), Telegram/Discord, forums, companies & sanctions (GLEIF, OpenSanctions, Swiss registers), news/RSS |
| **Cases** | graph view (Cytoscape), provenance per finding, Admiralty-style source/information rating, merge of duplicates, restricted cases (need-to-know), evidence capture (screenshot + hash) |
| **Monitoring** | scheduled re-runs, change detection, alerts by email or webhook |
| **Reports & export** | PDF/DOCX reports with configurable sections, CSV, Maltego, MISP, STIX 2.1 |
| **AI linking** (optional) | suggests links between entities via Gemini or a local OpenAI-compatible model (Ollama/vLLM) |
| **Accounts** | Keycloak (OIDC), TOTP, roles admin/investigator/reader, per-organisation IdP in multi-tenant mode |
| **Audit** | append-only, HMAC-chained audit log with external anchors; selectors can be stored hashed |
| **Languages** | UI and handbook in German, English, French, Italian |

Every API key is optional. Tools without a key either work keyless or
report a clear "key not configured" note instead of failing.

## Two ways to install

```
 allinone  — one server                    operator — framework for several organisations
┌──────────────────────────────┐          ┌──────────────────────┐     ┌────────────────────┐
│ framework (web, API, modules,│          │ framework            │ ──▶ │ data server org A  │
│ login)                       │          │ (web, API, modules,  │     │ DB + Keycloak + TLS│
│        │ internal network    │          │  operator console)   │     └────────────────────┘
│ data server (case database)  │          │                      │ ──▶ ┌────────────────────┐
└──────────────────────────────┘          └──────────────────────┘     │ data server org B  │
                                                                       └────────────────────┘
```

* **allinone** — one organisation, a team, an evaluation. Users log in
  through the framework's Keycloak. Works with an IP address (self-signed
  certificate) or a domain (Let's Encrypt).
* **operator** — you run the framework for several organisations; each
  installs its own data server with `data-agent/install.sh` and keeps its
  own users and case data. You never hold either.

## Quick start

Requirements: Debian 12 / Ubuntu 22.04+ (x86_64 or arm64), 8 GB RAM,
2 CPU cores, 40 GB disk, root access. Docker is installed by the setup if
missing.

```bash
git clone https://github.com/cybersecswiss/open-osint-framework.git /opt/oof
cd /opt/oof
sudo ./setup.sh
```

The guided setup asks for the language, the installation type, the
address and a few names, then builds and starts everything (first run:
15–40 minutes) and prints where to log in. Credentials end up in
`/root/oof-credentials.txt`.

Unattended example:

```bash
sudo ./setup.sh --lang en --mode allinone --host 203.0.113.10 \
     --admin-email admin@example.org --yes
```

Full walkthrough, all options and troubleshooting:
**[docs/install.en.md](docs/install.en.md)**.

## Documentation

| Document | For |
|---|---|
| [docs/install.en.md](docs/install.en.md) / [.de](docs/install.de.md) | installing (both modes), options, first login, troubleshooting |
| [docs/customer-server.en.md](docs/customer-server.en.md) / [.de](docs/customer-server.de.md) | an organisation installing its own data server (operator mode) |
| [docs/operations.en.md](docs/operations.en.md) / [.de](docs/operations.de.md) | API keys, users, backups, restore, updates, Telegram/GHunt, logs |
| [docs/architecture.md](docs/architecture.md) | how it is built: containers, trust zones, search path, module contract |
| In-app handbook (`/handbook`) | end users — DE/EN/FR/IT |
| [CONTRIBUTING.md](CONTRIBUTING.md) | development setup, adding a module, tests |

## Responsible use

OOF is a tool for lawful investigations: security research, fraud
and threat investigation, due diligence, journalism, law enforcement
within its legal mandate. Many of the integrated sources process personal
data. **You** are responsible for having a legal basis for every search,
for respecting the terms of service of the sources and API providers you
enable, and for data protection (GDPR / Swiss FADP or your local law). The
platform helps — purpose field, audit log, need-to-know cases, retention
settings — but it does not make a search lawful. See [DISCLAIMER.md](DISCLAIMER.md).

## Contact

Questions, cooperation, commercial use: **info@cybersecswiss.ch**
Security issues: see [SECURITY.md](SECURITY.md) — please not as a public issue.

## License

Copyright © 2026 Aljoscha T. — see [NOTICE](NOTICE).

[GNU Affero General Public License v3.0](LICENSE). If you run a modified
version as a network service, you must offer its source code to its users.
Third-party components and their licenses: [THIRD_PARTY.md](THIRD_PARTY.md).
