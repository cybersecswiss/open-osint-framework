# Installing OOF

[Deutsch](install.de.md) · back to [README](../README.md)

This guide takes you from an empty server to a working installation. The
setup script does the work; this page explains what it asks, what it does
and what to do when something goes wrong.

---

## 1. Choose the installation type

| | **allinone** | **operator** |
|---|---|---|
| Who | one organisation, a team, an evaluation | a provider serving several organisations |
| Case data | on the same server, in a separate data-server stack | on each organisation's own data server |
| User accounts | in the framework's Keycloak | in each organisation's own Keycloak |
| Address | IP address **or** domain | domain recommended (organisations' servers call it) |
| Afterwards | log in and work | create organisations in `/glbadmin`, they install [their data server](customer-server.en.md) |

If unsure: **allinone**. You cannot switch an existing installation from
one type to the other; install anew instead.

## 2. Requirements

| | Minimum | Notes |
|---|---|---|
| OS | Debian 12, Ubuntu 22.04 / 24.04 | other systemd Linuxes may work but are untested |
| CPU | 2 cores, x86_64 or arm64 | 4 cores make the first build twice as fast |
| RAM | 8 GB | ~30 containers; below 8 GB tools get killed under load |
| Disk | 40 GB free | images ~15 GB, plus data and backups |
| Network | outbound internet | for the build and for the OSINT sources |
| Ports | 443 and 80 (or two free alternatives) | the setup offers alternatives if they are taken |
| Access | root (`sudo`) | |

Docker and Docker Compose are installed automatically if missing.

Check a server without changing anything:

```bash
./setup.sh --check
```

### Domain and certificate

* **IP address** → a self-signed certificate is generated. Browsers show a
  warning once; accept it. Fine for internal use and evaluation.
* **Domain** → the setup can obtain a free **Let's Encrypt** certificate.
  Before you start, create a DNS `A` record pointing the name at the server,
  and make sure port **80** is reachable from the internet (the HTTP-01
  challenge). The certificate renews automatically.

## 3. Install

```bash
sudo apt-get install -y git          # if git is missing
sudo git clone https://github.com/cybersecswiss/open-osint-framework.git /opt/oof
cd /opt/oof
sudo ./setup.sh
```

The setup runs through twelve numbered steps:

| Step | What happens |
|---|---|
| 1 Prerequisites | memory, CPU, disk, internet, architecture |
| 2 Details | type, address, certificate, ports, names (see below) |
| 3 System | packages (curl, git, jq, openssl, python3, cron), Docker if missing |
| 4 Firewall | optional `ufw`: only SSH and the two web ports open |
| 5 Configuration | `.env` with ~20 generated secrets (`chmod 600`) |
| 6 Certificate | self-signed, or an interim one for Let's Encrypt |
| 7 Build & start | builds ~20 images and starts the stack (**15–40 min** the first time) |
| 8 Let's Encrypt | obtains the real certificate + renewal hook (domain only) |
| 9 Login | Keycloak realms `osint` (users) and `platform` (operator console) |
| 10 Organisation | allinone: creates your organisation, first user, local data server |
| 11 Datasets / release | downloads two forum indexes in the background; operator: publishes the data-server release at `/agent/` |
| 12 Verification | checks every part and writes the credentials file |

### The questions

| Question | Meaning |
|---|---|
| Language | language of the setup output (`en`/`de`) |
| Installation type | `allinone` or `operator` (section 1) |
| Public address | what users type into the browser: IP or DNS name. Detected automatically. |
| Let's Encrypt? | only asked for a domain |
| HTTPS port | asked only if 443 is taken (e.g. by another web server); default alternative 8443 |
| Operator email | Let's Encrypt notices; optional with a self-signed certificate |
| Product owner login | user name for the operator console `/glbadmin` (default `owner`) |
| *allinone only:* organisation id | short lowercase id, e.g. `main` |
| *allinone only:* first user + email | your administrator. **Users sign in with their email address**; its domain decides the organisation. |
| *allinone only:* email domains | all domains your users' addresses use, comma-separated |

### Unattended installation

Every question has a flag; `--yes` takes the defaults for the rest:

```bash
sudo ./setup.sh --lang en --mode allinone --host osint.example.org \
     --tls letsencrypt --email ops@example.org \
     --admin-email alice@example.org --email-domains example.org --yes
```

| Option | |
|---|---|
| `--lang en\|de` | setup language |
| `--mode allinone\|operator` | installation type |
| `--host NAME\|IP` | public address |
| `--tls selfsigned\|letsencrypt` | certificate type |
| `--http-port N`, `--https-port N` | ports (default 80/443) |
| `--email ADDR` | operator contact |
| `--owner-user NAME` | product owner login (default `owner`) |
| `--tenant ID`, `--admin-user NAME`, `--admin-email ADDR`, `--email-domains LIST` | allinone organisation and first user |
| `--no-firewall` | do not touch the firewall |
| `--skip-datasets` | do not download the forum indexes |
| `--skip-release` | operator: do not publish the data-server release |
| `--reconfigure` | re-ask address, ports and certificate on a re-run |
| `--check` | check the server only |
| `--yes` | unattended |

## 4. First login

The setup ends with the addresses and writes all credentials to
**`/root/oof-credentials.txt`** (readable by root only):

```bash
sudo cat /root/oof-credentials.txt
```

* **Web application** `https://<address>/` — *allinone*: sign in with the
  first user's **email address** and the generated password. At the first
  login you choose your own password and enrol an authenticator app (TOTP,
  e.g. Aegis, Google Authenticator, 1Password).
* **Operator console** `https://<address>/glbadmin` — product-owner
  account: API keys, organisations, licences, news feeds, forum lists.
* **Keycloak administration** `https://<address>/auth/admin/` — only for
  special cases; users are normally managed in the app (Admin → User Management).
* **Grafana** `https://<address>/grafana/` — container metrics.

Move the credentials into a password manager and delete the file.

## 5. Right after the installation

1. **API keys** (optional) — `/glbadmin` → *Settings*. Each key has a
   *Test* button. Start with the free ones: abuse.ch, AlienVault OTX,
   VirusTotal, AbuseIPDB, Etherscan. Details: [operations](operations.en.md#api-keys).
2. **Users** — in the app: *Admin → User Management → New user*. Their email domain
   must be one of the organisation's domains (operator console →
   organisation → email domains).
3. **Backups** — [operations → backups](operations.en.md#backups). Without
   a copy elsewhere, a disk failure loses every case.
4. **Operator mode** — create the first organisation and send its IT the
   [data-server guide](customer-server.en.md).

## 6. Updating, re-running, changing the address

```bash
cd /opt/oof
sudo git pull
sudo ./setup.sh          # repairs + updates; secrets and data are kept
```

New address or ports (e.g. a domain instead of the IP):

```bash
sudo ./setup.sh --reconfigure
```

This regenerates the certificate if needed and rebuilds the web frontend,
which has the address compiled in.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Setup stops at step 7 (build) | full log: `/var/log/oof-build.log`. Usually a network hiccup while downloading — just run `sudo ./setup.sh` again; finished images are reused. |
| "Port … is taken" | another web server uses it. Free it, or answer the port question with a free port (`--https-port 8443 --http-port 8080`). |
| Let's Encrypt failed | DNS does not point at the server yet, or port 80 is blocked by a cloud firewall. Fix it and re-run; the interim certificate keeps working meanwhile. Log: `/var/log/oof-certbot.log`. |
| Browser: "connection not private" | expected with a self-signed certificate — accept it once. |
| Login page loops / "invalid redirect" | the address in the browser differs from the configured one (e.g. IP vs. name, missing port). Use exactly the URL the setup printed, or change it with `--reconfigure`. |
| "Your organisation is not registered" | the email domain is not assigned to an organisation. Operator console → organisation → email domains. |
| 502 Bad Gateway on a page | a container is (re)starting. `docker compose ps`; wait 30 s; `docker compose logs <service>`. |
| Searches return fewer results than expected | memory pressure (`docker stats`, `dmesg | grep -i oom`), or the tool needs an API key (the result notes say so). |
| Keycloak setup failed (step 9) | `/var/log/oof-keycloak.log`; Keycloak needs ~2 min on the first start — re-run the setup. |

Health overview at any time:

```bash
cd /opt/oof && bash scripts/health-check.sh
```

## 8. Uninstalling

```bash
cd /opt/oof
docker compose down                       # stop, keep data
(cd data-agent && docker compose -f docker-compose.yml -f docker-compose.local.yml down)
# Deletes ALL data irreversibly — cases, users, settings:
docker compose down -v
(cd data-agent && docker compose -f docker-compose.yml -f docker-compose.local.yml down -v)
```
