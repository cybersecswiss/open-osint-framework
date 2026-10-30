# Third-party components

OOF does not vendor third-party tools: they are downloaded from their
upstream sources when the Docker images are **built** on your server, and
the container images listed below are pulled from their registries. Each
remains under its own license. The table lists the main ones; the complete
dependency lists are the `requirements.txt` files, `frontend/package.json`
and the `Dockerfile`s. Licenses as published upstream at the time of
writing — check the upstream project before redistributing images.

## OSINT tools (installed at build time)

| Component | Used by | License |
|---|---|---|
| [Sherlock](https://github.com/sherlock-project/sherlock) | module-alias | MIT |
| [WhatsMyName](https://github.com/WebBreacher/WhatsMyName) data | module-alias | CC BY-SA 4.0 |
| [user-scanner](https://pypi.org/project/user-scanner/), [linkook](https://pypi.org/project/linkook/) | module-alias | see upstream |
| [Holehe](https://github.com/megadose/holehe) | module-leaks | GPL-3.0 |
| [GHunt](https://github.com/mxrch/GHunt) | module-leaks | AGPL-3.0 |
| [subfinder](https://github.com/projectdiscovery/subfinder) | module-infra | MIT |
| [theHarvester](https://github.com/laramies/theHarvester) | module-infra | GPL-2.0 |
| [dnstwist](https://github.com/elceef/dnstwist) | module-infra | Apache-2.0 |
| [python-whois](https://pypi.org/project/python-whois/) | module-infra | MIT |
| [Telethon](https://github.com/LonamiWebs/Telethon) | module-messenger, module-telegram | MIT |
| [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) | module-messenger | Apache-2.0 |
| Tor | tor | BSD-3-Clause |

## Infrastructure images

| Image | License |
|---|---|
| PostgreSQL (`postgres:16-alpine`) | PostgreSQL License |
| Redis (`redis:7-alpine`) | BSD-3-Clause up to 7.2; RSALv2/SSPLv1 from 7.4 — pin `redis:7.2-alpine` if you need an OSI license |
| Keycloak (`quay.io/keycloak/keycloak:24.0`) | Apache-2.0 |
| nginx (`nginx:alpine`) | BSD-2-Clause |
| Caddy (`caddy:2-alpine`, data server) | Apache-2.0 |
| n8n (built from `n8nio/n8n`) | Sustainable Use License (fair-code, **not** OSI-approved) — used unmodified for the AI workflows; check its terms for commercial hosting |
| Prometheus | Apache-2.0 |
| Grafana | AGPL-3.0 |
| Chromium (capture) | BSD-3-Clause and others |

## Frontend libraries

React (MIT), Ant Design (MIT), Cytoscape.js (MIT), TanStack Query (MIT),
i18next (MIT), Vite (MIT) — see `frontend/package.json`.

## Data sources

The modules query external services (e.g. VirusTotal, abuse.ch, HIBP,
OpenSanctions, GLEIF, crt.sh, Etherscan). Their data is subject to their
own terms of service, which you accept when you configure and use them.
The forum indexes (`modules/forums/data/README.md`) are downloaded from
their sources at setup time and are not part of this repository.
