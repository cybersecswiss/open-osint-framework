# Setting up your data server (operator mode)

[Deutsch](customer-server.de.md) · back to [README](../README.md)

**For the IT department of an organisation that uses a OOF framework
run by someone else (the *operator*). Read it in full before you start.**

> Running OOF for yourself on one server? Then you do **not** need
> this page — use `setup.sh --mode allinone` ([install guide](install.en.md)).

---

## 1. What this is

You set up a server on which **your investigation data lives — and only
there**. The operator runs the search framework; cases, entities and
relations are stored exclusively on this server, in your own database,
behind your own login service (Keycloak).

> **The operator has no administrative access to this server and no copy
> of your passwords.** Nobody but you can reset a password or recover
> deleted case files.

## 2. What to prepare

| | Requirement | Note |
|---|---|---|
| Server | Debian 12 or Ubuntu 22.04/24.04, fresh | x86_64 |
| Memory / disk | 4 GB / 20 GB free | 8 GB recommended |
| Access | root or `sudo` | |
| Address | a **DNS name** pointing here (recommended) **or** an IP address | see below |
| Ports | 443 (and 80 for Let's Encrypt) reachable by the framework and your users | other ports possible |
| From the operator | **framework address** (e.g. `https://osint.example.org`) and **licence key** | |
| Email | for certificate notices and the first administrator | |

### DNS name or IP address?

* **DNS name + Let's Encrypt** (recommended for anything reachable over the
  internet): create the `A` record first and check it:
  `dig +short data.example.org` must print this server's IP. Port 80 must be
  reachable from the internet for the certificate challenge.
* **IP address or internal name** (LAN, test): the data server gets a
  **self-signed** certificate. The operator must then set
  `TLS_VERIFY_AGENT=false` and `TLS_VERIFY_IDP=false` on the framework, and
  your users' browsers will warn once on the login page.

## 3. Installation

```bash
curl -fsSL https://<framework-address>/agent/install.sh -o install.sh
sudo bash install.sh
```

If the **framework** uses a self-signed certificate, download with
`curl -fsSLk …` and answer *yes* when the installer asks whether to accept
it — only if the operator told you so.

The installer asks for the language, then walks through ten steps:

| Step | What happens |
|---|---|
| 1 Prerequisites | memory, disk, internet |
| 2 Existing installation | a re-run repairs; passwords are never regenerated |
| 3 Details | framework address, licence key, address of this server, certificate type, ports, email, first administrator |
| 4 Licence | validated with the framework; your access key is fetched |
| 5 System | Docker is installed if missing |
| 6 Program files | downloaded and **checked against the release checksums** |
| 7 Configuration | passwords generated, login realm prepared |
| 8 Services | database, data server, Keycloak, TLS proxy (Caddy) |
| 9 Backups | daily at 02:15, 30 kept |
| 10 Verification | including HTTPS |

Duration: 5–15 minutes.

Unattended:

```bash
sudo bash install.sh --lang en --framework-url https://osint.example.org \
     --license-key '<KEY>' --host data.example.org --tls letsencrypt \
     --email it@example.org --admin-email admin@example.org --yes
```

Further options: `--tls internal` (self-signed), `--https-port 8443`,
`--http-port 8080`, `--admin-user NAME`, `--insecure-framework`,
`--install-dir DIR` — `bash install.sh --help`.

## 4. Afterwards

### 4.1 Send the operator three items

```
Data server:  https://data.example.org
Login:        https://data.example.org/auth/realms/<tenant>
Tenant:       <tenant>
```

They contain no secret. The operator enters them in the console; only then
can your users log in.

### 4.2 Store the credentials

```bash
sudo cat /root/oof-agent-credentials.txt
```

* **Keycloak master administrator** — manages the login service
* **First administrator of your organisation** — creates the other accounts;
  must change the password at the first login

Move them into your password manager and delete the file.

### 4.3 First login

1. Open the framework address in the browser.
2. Enter your work email address — you are sent to **your** login service.
3. Sign in as the first administrator.

Further users: in the app under *Admin → User Management*, or in your
Keycloak at `https://<your-address>/auth/admin/` → realm `<tenant>` → Users.

## 5. Day-to-day operation

```bash
cd /opt/oof-agent
sudo docker compose ps              # everything running?
sudo docker compose logs -f agent   # follow the log
sudo ./backup.sh                    # back up now
sudo ./update.sh --check            # is there an update?
sudo ./update.sh                    # install it
```

**Backups** are written to `/opt/oof-agent/backups/` on this same
server. Only a copy elsewhere protects against a disk failure — include the
directory in your existing backup routine.

**Updates** — `update.sh` compares versions, backs up first, verifies every
file against the checksums, starts the new version and **rolls back
automatically** if it does not come up healthy. Case data is not touched.
Automatic, e.g. every Sunday 03:00:

```bash
sudo crontab -e
0 3 * * 0 cd /opt/oof-agent && ./update.sh --yes >> /var/log/oof-update.log 2>&1
```

## 6. Troubleshooting

| Message / symptom | Cause and remedy |
|---|---|
| "The framework is unreachable" | wrong address, no internet, or the operator has not published a release yet (`bash scripts/release.sh` on the framework). Test: `curl -I https://<framework>/agent/version.json` |
| "TLS certificate is not trusted" | the framework uses a self-signed certificate. Accept only if the operator confirmed it (`--insecure-framework`). |
| "Licence invalid" | wrong key, expired or deactivated licence — ask the operator. |
| "Port … is in use" | another web server runs here. Stop it, or use `--https-port`/`--tls internal`. |
| "https://… is not answering yet" | DNS not pointing here yet, port 80/443 blocked upstream, Let's Encrypt still working. `docker compose logs proxy` |
| "Checksum mismatch" | a file was altered in transit or the release is inconsistent. **Stop** and contact the operator. |
| Login does not work | the operator has not registered your addresses yet — or, with a self-signed certificate, `TLS_VERIFY_IDP=false` is missing on the framework. |

For a fault report, send:

```bash
cd /opt/oof-agent
sudo docker compose ps
sudo docker compose logs --tail 100 agent
cat .installed-version.json
```

**Never send `.env` or files from `backups/`** — they hold passwords and
case data.

## 7. Removal

```bash
cd /opt/oof-agent
sudo ./backup.sh                # one last backup
sudo docker compose down        # stop (data stays)
sudo docker compose down -v     # ⚠ DELETES ALL DATA IRREVERSIBLY
```
