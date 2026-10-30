# Operating OOF

[Deutsch](operations.de.md) · back to [README](../README.md)

Everyday administration of an installed framework. All commands run in the
installation directory (default `/opt/oof`) as root or a member of
the `docker` group.

- [Everyday commands](#everyday-commands)
- [API keys](#api-keys)
- [Users and roles](#users-and-roles)
- [Organisations (operator mode)](#organisations-operator-mode)
- [Backups](#backups)
- [Restore](#restore)
- [Updates](#updates)
- [Sensitive tools — off by default](#sensitive-tools--off-by-default)
- [Telegram, GHunt, AI](#telegram-ghunt-ai)
- [Forum indexes](#forum-indexes)
- [Secrets — what must never change](#secrets--what-must-never-change)
- [Troubleshooting](#troubleshooting)

---

## Everyday commands

```bash
cd /opt/oof
docker compose ps                         # what runs
bash scripts/health-check.sh              # full health report
docker compose logs -f --tail 100 api     # follow a service (api, frontend, keycloak, module-leaks, …)
docker compose restart module-alias       # restart one service
bash scripts/rebuild.sh api               # rebuild + recreate a service without nginx 502s
docker stats --no-stream                  # memory per container
```

All-in-one data server (case database):

```bash
cd /opt/oof/data-agent
docker compose -f docker-compose.yml -f docker-compose.local.yml ps
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f agent
```

Setup logs: `/var/log/oof-build.log`, `-keycloak.log`, `-certbot.log`,
`-release.log`.

## API keys

Every key is optional. Enter them in the **operator console**
`/glbadmin` → *Settings*: grouped by area, each with a *Test* button that
queries the real provider. Keys are stored encrypted (Fernet, key
`APIKEY_KEK`) in the license-server database and take effect immediately —
no restart. A value in `.env` still works as a fallback; one set in the
console wins.

| Key | Tools | Where | Cost |
|---|---|---|---|
| abuse.ch (`ABUSECH_API_KEY`) | ThreatFox, MalwareBazaar, URLhaus | https://auth.abuse.ch/ | free |
| AlienVault OTX | otx | https://otx.alienvault.com/ | free |
| VirusTotal | virustotal | https://www.virustotal.com/gui/my-apikey | free tier |
| AbuseIPDB | abuseipdb | https://www.abuseipdb.com/account/api | free tier |
| GreyNoise | greynoise | https://viz.greynoise.io/account | free tier |
| Shodan | shodan, favicon pivots | https://account.shodan.io/ | paid / membership |
| Etherscan | etherscan | https://etherscan.io/apis | free tier |
| Have I Been Pwned | hibp | https://haveibeenpwned.com/API/Key | paid |
| Intelligence X | intelx | https://intelx.io/ | free tier / paid |
| OpenSanctions | opensanctions | https://www.opensanctions.org/api/ | key, or self-host *yente* (`OPENSANCTIONS_BASE`) |
| Brave Search | forum/news hunts | https://brave.com/search/api/ | free tier |
| Gemini | AI linking | https://aistudio.google.com/ | free tier |
| Telegram API / session | deep Telegram collection | see below | free |

The console shows the exact list of the installed version. A new key type
is one `KEY_REGISTRY` entry in `backend/app/services/api_keys.py`.


## Users and roles

| Role | May |
|---|---|
| `reader` | read cases |
| `investigator` | search, create and edit cases |
| `admin` | plus user management and organisation settings |
| product owner (`platform` realm) | operator console `/glbadmin` only — no access to case data |

* **All-in-one:** users live in the framework's Keycloak (realm `osint`).
  Create them in the app: *Admin → User Management → New user*. Their email
  domain must be one of the organisation's email domains.
* **Operator mode:** each organisation manages its own users in its own
  Keycloak; you cannot.
* New users must set a password and enrol TOTP at their first login.
* Password reset: *Admin → User Management*, or Keycloak admin
  (`/auth/admin/`, realm `osint`) → Users → Credentials.
* Additional product owners: Keycloak admin → realm `platform` → Users,
  role `platform_admin`.

## Organisations (operator mode)

1. `/glbadmin` → *Authorities* → *New*: id (lowercase), name, contact
   email, email domains. The licence key is shown **once** — send it to the
   organisation's IT together with the framework address and
   [docs/customer-server.en.md](customer-server.en.md).
2. The organisation installs its data server and sends back the
   *data server URL*, *login URL* and *tenant*.
3. Enter both URLs at the organisation (*Data server URL*, *IdP URL*). From
   then on its users can sign in with their email address.
4. Data servers with a self-signed certificate require, in `.env`:
   `TLS_VERIFY_AGENT=false` and `TLS_VERIFY_IDP=false`, then
   `docker compose up -d api`. These switches are global — prefer real
   certificates.

Data-server releases: `bash scripts/release.sh` builds the data-server
image and publishes it with checksums at `https://<framework>/agent/`.
Run it after every update of the framework; organisations then update with
`sudo ./update.sh` on their server. Bump `VERSION` (scheme `YYYY.MM.N`)
for each release.

## Backups

`scripts/backup.sh` dumps all databases (framework **and**, in all-in-one,
the case database) plus the data volumes into a dated directory, and
deletes those older than `RETENTION_DAYS` (30).

```bash
sudo BACKUP_ROOT=/var/backups/oof bash scripts/backup.sh
```

Schedule it daily (root crontab, `crontab -e`) through the wrapper that
records success, so a backup that silently stops is noticed:

```
15 2 * * * cd /opt/oof && BACKUP_ROOT=/var/backups/oof bash scripts/run-scheduled.sh backup bash scripts/backup.sh >> /var/log/oof-backup.log 2>&1
```

`bash scripts/backup-watchdog.sh` (also part of `health-check.sh`) reports
a backup older than 30 h as a problem.

**Also back up, separately and securely:** `.env` and `certs/`. Without
`.env` (`APIKEY_KEK`, `LICENSE_KEK`, `AUDIT_HMAC_KEY`) a database dump is
only partly usable. `bash scripts/make-dr-archive.sh /some/dir` writes one
file with code, `.env`, certificates and all data — the complete
disaster-recovery set. Treat it like the passwords it contains.

**Copy backups off the server** (another host, object storage). A backup on
the same disk does not survive the disk.

## Restore

```bash
bash scripts/restore.sh latest                       # framework databases + volumes
bash scripts/restore.sh /var/backups/oof/2026-10-30_021501
bash scripts/restore-agent.sh latest                 # all-in-one: the case database
```

Onto a new server: install the same version with `setup.sh`, copy the old
`.env` and `certs/` over the new ones **before** restoring, then
`docker compose up -d` and restore.

## Updates

```bash
cd /opt/oof
bash scripts/backup.sh          # first
git pull
sudo ./setup.sh                 # rebuilds what changed, migrates, keeps secrets
```

Database migrations (Alembic) run automatically when the `api` starts.
Roll back to the previous images and commit: `bash scripts/rollback.sh`.
Operator mode: afterwards `bash scripts/release.sh` for the data servers.

## Sensitive tools — off by default

Three tools are disabled in every fresh installation. While a switch is
`false` the tool does not appear in the search form and direct calls are
refused. Enable one only if you have a legal basis for its use:

| Switch in `.env` | Tool | Why it is off |
|---|---|---|
| `ENABLE_ORIGIN_RESOLVE=true` | `origin_resolve` (infra) | finds the real server behind a CDN by probing candidate addresses **directly from your server**, including third-party hosts — visible to the target |
| `ENABLE_ONION_SCRAPE=true` | `onion_scrape` (darknet) | reads the text content of hidden services over Tor. Services on Ahmia's abuse blacklist are always refused; nothing is fetched if the list cannot be loaded |
| `ENABLE_DATING_SEARCH=true` | `cupidcrawl` (dating) | ⚠️ checks usernames on dating and adult platforms — results are information about a person's **sex life** (special category, FADP art. 5 c / GDPR art. 9) |

Apply a change with:

```bash
docker compose up -d module-infra module-darknet module-dating
```

## Telegram, GHunt, AI

**Telegram.** Keyless search works out of the box (public web preview).
The deep path (full history, search inside channels, translation, media)
needs a dedicated Telegram account:

1. https://my.telegram.org/apps → `api_id`, `api_hash`.
2. Create a session once, interactively (phone + code):
   ```bash
   pip install telethon
   TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=abc… python3 scripts/telegram-session.py
   ```
3. Enter the three values in `/glbadmin` → *Settings* → Telegram (or
   `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` in `.env`),
   then `docker compose up -d --force-recreate module-messenger module-telegram`.

The channel list for the username hunt is
`modules/messenger/config/crime_channels.txt` (also editable in the console).

**GHunt** (Google accounts) needs a Google session of a *burner* account:
`python3 scripts/ghunt-session.py` walks you through it; paste the printed
master token into the console (Settings → Google).

**AI linking.** Default provider Gemini (key in the console). For a local,
sovereign model: in `.env` set `AI_PROVIDER=local`,
`AI_LOCAL_BASE_URL=http://<ollama-host>:11434/v1`, `AI_LOCAL_MODEL=llama3.1`,
then `docker compose up -d api n8n` and activate the workflow
*ai-link-local* in n8n (`/n8n/`).

## Forum indexes

`threat_actor_check` and `linkbase_lookup` use two indexes compiled from
public third-party sources. They are not shipped; `setup.sh` starts the
download. Refresh at any time in the console (Settings → indexes) or:

```bash
docker compose exec module-forums curl -fsS -X POST localhost:8110/threat-actors/refresh
docker compose exec module-forums curl -fsS -X POST localhost:8110/linkbase/refresh
docker compose exec module-forums curl -fsS localhost:8110/threat-actors/status
```

## Secrets — what must never change

`.env` holds every secret. Some may be rotated, three must not be edited:

| Variable | If changed |
|---|---|
| `APIKEY_KEK` | all API keys stored in the console become unreadable. Rotate only with `scripts/rekey-apikeys.py` (instructions in `.env.example`). |
| `LICENSE_KEK` | stored customer secrets (SMTP password, webhook secrets, IdP secrets) become unreadable — no re-encryption path. |
| `AUDIT_HMAC_KEY` | new audit entries no longer chain to old ones. |
| `POSTGRES_*_PASSWORD` | the database still has the old password — change it in Postgres first. |

Keycloak client secrets (`KEYCLOAK_CLIENT_SECRET`, `PLATFORM_KC_CLIENT_SECRET`)
can be changed: edit `.env`, re-run `sudo ./setup.sh`.

## Troubleshooting

| Symptom | Look at |
|---|---|
| 502 on a page | `docker compose ps` — a container restarting; `docker compose logs <service>` |
| login loop / "invalid redirect" | browser URL must equal `https://PUBLIC_HOST[:PORT]` from `.env`; change with `setup.sh --reconfigure` |
| "organisation not registered" | email domain missing at the organisation (console) |
| results missing | memory (`docker stats`, `dmesg \| grep -i oom`), API key not set (result notes), rate limits of the source |
| frontend shows old version | the address is compiled in: `docker compose build --no-cache frontend && docker compose up -d frontend` |
| case data not saved (all-in-one) | `docker compose exec api python -c "import httpx;print(httpx.get('http://data-agent-local:9000/health').text)"` and the data-agent logs |
| disk full | `docker system df`; `docker builder prune` frees the build cache |
