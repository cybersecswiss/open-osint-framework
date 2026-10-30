# Contributing

Thanks for helping. Issues and pull requests are welcome — for anything
larger than a fix, open an issue first so we can agree on the approach.

## Development setup

Easiest is a VM or spare server with the all-in-one install:

```bash
git clone https://github.com/cybersecswiss/open-osint-framework.git && cd open-osint-framework
sudo ./setup.sh --mode allinone --host <vm-ip> --admin-email you@example.org --yes
```

After changing code, rebuild just that service:

```bash
bash scripts/rebuild.sh api            # backend
bash scripts/rebuild.sh module-infra   # a module
docker compose build --no-cache frontend && docker compose up -d frontend
```

`ALLOW_PASSWORD_GRANT=1 PLATFORM_PASSWORD=… bash scripts/configure-keycloak.sh`
enables the OAuth password grant for scripted API tests (never in production).

## Checks

```bash
cd frontend && npm ci && npm run build        # type check + production build
```

CI (`.github/workflows/ci.yml`) runs ShellCheck, the frontend build and a
gitleaks scan on every push and pull request.

## Adding an OSINT tool or module

Modules are small FastAPI services that describe themselves: `GET /manifest`
lists their tools, accepted query types and latency class; `POST /run`
executes. The contract is in `modules/base/schemas.py`, the background in
[docs/architecture.md](docs/architecture.md) §6. In short:

1. Add a `tools/<name>_runner.py` returning `Finding`s and
   `EdgeResult`s. Entities are `entity_type:label`; keep `entity_type`
   ≤ 30 characters and reuse existing types (`graph_builder` canonicalises
   them — a new spelling creates shadow nodes).
2. Register the tool in the module's manifest, add translations for its
   `label_key`/`description_key` to `frontend/public/locales/*/common.json`.
3. Give it a source rating (Admiralty reliability).
4. Keys: a new API key is one `KEY_REGISTRY` entry in
   `backend/app/services/api_keys.py`; tools must degrade to a clear
   "not configured" note without it.

A whole new module also needs a service in `docker-compose.yml`, a
`MODULE_<NAME>_URL` (`.env.example`, `backend/app/config.py`) and an entry
in `MODULE_REGISTRY` in `backend/app/services/osint_orchestrator.py`.

## Rules of the house

* The data server is the only place case data is stored. Do not add code
  paths that keep entities on the framework side.
* No secrets, real personal data or customer names in code, tests or
  fixtures. Use `example.org` / `agency.example`.
* Scripts: `bash`, `set -euo pipefail`, ShellCheck-clean, output via
  `scripts/lib/guide.sh` (bilingual `L "english" "deutsch"`).
* User-visible changes get an entry in `frontend/public/wiki/changelog.json`.

By contributing you agree that your contribution is licensed under the
AGPL-3.0.
