# OOF betreiben

[English](operations.en.md) · zurück zum [README](../README.de.md)

Die tägliche Verwaltung eines installierten Frameworks. Alle Befehle im
Installationsverzeichnis (Vorgabe `/opt/oof`) als root oder als
Mitglied der Gruppe `docker`.

- [Alltägliche Befehle](#alltägliche-befehle)
- [API-Schlüssel](#api-schlüssel)
- [Benutzer und Rollen](#benutzer-und-rollen)
- [Organisationen (Betreibermodus)](#organisationen-betreibermodus)
- [Sicherung](#sicherung)
- [Wiederherstellung](#wiederherstellung)
- [Updates](#updates)
- [Heikle Werkzeuge — ab Werk aus](#heikle-werkzeuge--ab-werk-aus)
- [Telegram, GHunt, KI](#telegram-ghunt-ki)
- [Foren-Indizes](#foren-indizes)
- [Geheimnisse — was sich nie ändern darf](#geheimnisse--was-sich-nie-ändern-darf)
- [Fehlerbehebung](#fehlerbehebung)

---

## Alltägliche Befehle

```bash
cd /opt/oof
docker compose ps                         # was läuft
bash scripts/health-check.sh              # vollständiger Zustandsbericht
docker compose logs -f --tail 100 api     # Dienst mitlesen (api, frontend, keycloak, module-leaks, …)
docker compose restart module-alias       # einen Dienst neu starten
bash scripts/rebuild.sh api               # Dienst neu bauen + ersetzen ohne nginx-502
docker stats --no-stream                  # Speicher je Container
```

All-in-one-Datenserver (Falldatenbank):

```bash
cd /opt/oof/data-agent
docker compose -f docker-compose.yml -f docker-compose.local.yml ps
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f agent
```

Setup-Logs: `/var/log/oof-build.log`, `-keycloak.log`, `-certbot.log`,
`-release.log`.

## API-Schlüssel

Jeder Schlüssel ist optional. Eintragen in der **Betreiberkonsole**
`/glbadmin` → *Einstellungen*: nach Bereich gruppiert, jeweils mit
*Test*-Knopf, der beim echten Anbieter nachfragt. Die Schlüssel liegen
verschlüsselt (Fernet, Schlüssel `APIKEY_KEK`) in der Datenbank des
Lizenzservers und wirken sofort — ohne Neustart. Ein Wert in `.env` gilt
weiterhin als Rückfall; ein in der Konsole gesetzter hat Vorrang.

| Schlüssel | Werkzeuge | Wo | Kosten |
|---|---|---|---|
| abuse.ch (`ABUSECH_API_KEY`) | ThreatFox, MalwareBazaar, URLhaus | https://auth.abuse.ch/ | kostenlos |
| AlienVault OTX | otx | https://otx.alienvault.com/ | kostenlos |
| VirusTotal | virustotal | https://www.virustotal.com/gui/my-apikey | Gratisstufe |
| AbuseIPDB | abuseipdb | https://www.abuseipdb.com/account/api | Gratisstufe |
| GreyNoise | greynoise | https://viz.greynoise.io/account | Gratisstufe |
| Shodan | shodan, Favicon-Pivots | https://account.shodan.io/ | kostenpflichtig / Membership |
| Etherscan | etherscan | https://etherscan.io/apis | Gratisstufe |
| Have I Been Pwned | hibp | https://haveibeenpwned.com/API/Key | kostenpflichtig |
| Intelligence X | intelx | https://intelx.io/ | Gratisstufe / kostenpflichtig |
| OpenSanctions | opensanctions | https://www.opensanctions.org/api/ | Schlüssel, oder *yente* selbst betreiben (`OPENSANCTIONS_BASE`) |
| Brave Search | Foren-/News-Suchen | https://brave.com/search/api/ | Gratisstufe |
| Gemini | KI-Verknüpfung | https://aistudio.google.com/ | Gratisstufe |
| Telegram-API / Session | Telegram-Tiefensuche | siehe unten | kostenlos |

Die Konsole zeigt die genaue Liste der installierten Version. Ein neuer
Schlüsseltyp ist ein `KEY_REGISTRY`-Eintrag in
`backend/app/services/api_keys.py`.


## Benutzer und Rollen

| Rolle | Darf |
|---|---|
| `reader` | Fälle lesen |
| `investigator` | suchen, Fälle anlegen und bearbeiten |
| `admin` | zusätzlich Benutzerverwaltung und Organisationseinstellungen |
| Product Owner (Realm `platform`) | nur die Betreiberkonsole `/glbadmin` — kein Zugriff auf Falldaten |

* **All-in-one:** Benutzer liegen im Keycloak des Frameworks (Realm
  `osint`). Anlegen in der App: *Admin → Benutzerverwaltung → Neuer
  Benutzer*. Die E-Mail-Domain muss zu den Domains der Organisation
  gehören.
* **Betreibermodus:** jede Organisation verwaltet ihre Benutzer in ihrem
  eigenen Keycloak; Sie können das nicht.
* Neue Benutzer setzen bei der ersten Anmeldung ein Passwort und richten
  TOTP ein.
* Passwort zurücksetzen: *Admin → Benutzerverwaltung*, oder in der
  Keycloak-Verwaltung (`/auth/admin/`, Realm `osint`) → Users → Credentials.
* Weitere Product Owner: Keycloak-Verwaltung → Realm `platform` → Users,
  Rolle `platform_admin`.

## Organisationen (Betreibermodus)

1. `/glbadmin` → *Behörden* → *Neu*: ID (Kleinbuchstaben), Name,
   Kontakt-E-Mail, E-Mail-Domains. Der Lizenzschlüssel wird **einmal**
   angezeigt — zusammen mit der Framework-Adresse und
   [docs/customer-server.de.md](customer-server.de.md) an die IT der
   Organisation senden.
2. Die Organisation installiert ihren Datenserver und meldet
   *Datenserver-URL*, *Login-URL* und *Mandant* zurück.
3. Beide URLs bei der Organisation eintragen (*Datenserver-URL*,
   *IdP-URL*). Ab dann melden sich ihre Benutzer mit der E-Mail-Adresse an.
4. Datenserver mit selbstsigniertem Zertifikat brauchen in `.env`:
   `TLS_VERIFY_AGENT=false` und `TLS_VERIFY_IDP=false`, danach
   `docker compose up -d api`. Diese Schalter gelten global — echte
   Zertifikate sind vorzuziehen.

Datenserver-Releases: `bash scripts/release.sh` baut das
Datenserver-Image und veröffentlicht es mit Prüfsummen unter
`https://<framework>/agent/`. Nach jedem Framework-Update ausführen; die
Organisationen aktualisieren dann mit `sudo ./update.sh` auf ihrem Server.
Für jedes Release `VERSION` erhöhen (Schema `JJJJ.MM.N`).

## Sicherung

`scripts/backup.sh` sichert alle Datenbanken (Framework **und** bei
All-in-one die Falldatenbank) sowie die Datenvolumes in ein datiertes
Verzeichnis und löscht solche, die älter als `RETENTION_DAYS` (30) sind.

```bash
sudo BACKUP_ROOT=/var/backups/oof bash scripts/backup.sh
```

Täglich einplanen (root-Crontab, `crontab -e`) über den Wrapper, der den
Erfolg festhält — so fällt eine still ausbleibende Sicherung auf:

```
15 2 * * * cd /opt/oof && BACKUP_ROOT=/var/backups/oof bash scripts/run-scheduled.sh backup bash scripts/backup.sh >> /var/log/oof-backup.log 2>&1
```

`bash scripts/backup-watchdog.sh` (auch Teil von `health-check.sh`) meldet
eine Sicherung, die älter als 30 h ist, als Problem.

**Zusätzlich, getrennt und sicher aufbewahren:** `.env` und `certs/`. Ohne
`.env` (`APIKEY_KEK`, `LICENSE_KEK`, `AUDIT_HMAC_KEY`) ist ein
Datenbank-Dump nur teilweise brauchbar. `bash scripts/make-dr-archive.sh
/ein/verzeichnis` schreibt eine Datei mit Code, `.env`, Zertifikaten und
allen Daten — den vollständigen Notfall-Satz. Behandeln Sie sie wie die
Passwörter, die sie enthält.

**Sicherungen vom Server wegkopieren** (anderer Host, Object Storage). Eine
Sicherung auf derselben Platte überlebt die Platte nicht.

## Wiederherstellung

```bash
bash scripts/restore.sh latest                       # Framework-Datenbanken + Volumes
bash scripts/restore.sh /var/backups/oof/2026-10-30_021501
bash scripts/restore-agent.sh latest                 # All-in-one: die Falldatenbank
```

Auf einen neuen Server: dieselbe Version mit `setup.sh` installieren, die
alte `.env` und `certs/` **vor** der Wiederherstellung über die neuen
kopieren, dann `docker compose up -d` und wiederherstellen.

## Updates

```bash
cd /opt/oof
bash scripts/backup.sh          # zuerst
git pull
sudo ./setup.sh                 # baut Geändertes neu, migriert, behält Geheimnisse
```

Datenbank-Migrationen (Alembic) laufen beim Start der `api` automatisch.
Zurück auf die vorherigen Images und den vorherigen Commit:
`bash scripts/rollback.sh`. Betreibermodus: danach `bash scripts/release.sh`
für die Datenserver.

## Heikle Werkzeuge — ab Werk aus

Drei Werkzeuge sind in jeder Neuinstallation deaktiviert. Solange ein
Schalter `false` ist, erscheint das Werkzeug nicht in der Suchmaske, und
direkte Aufrufe werden abgelehnt. Schalten Sie eines nur ein, wenn Sie
eine Rechtsgrundlage für den Einsatz haben:

| Schalter in `.env` | Werkzeug | Warum es aus ist |
|---|---|---|
| `ENABLE_ORIGIN_RESOLVE=true` | `origin_resolve` (infra) | findet den echten Server hinter einem CDN, indem es Kandidaten-Adressen **direkt von Ihrem Server aus** abfragt, auch Server Dritter — für das Ziel sichtbar |
| `ENABLE_ONION_SCRAPE=true` | `onion_scrape` (darknet) | liest den Textinhalt von Hidden Services über Tor. Dienste auf Ahmias Missbrauchs-Sperrliste werden immer abgelehnt; ist die Liste nicht ladbar, wird nichts abgerufen |
| `ENABLE_DATING_SEARCH=true` | `cupidcrawl` (dating) | ⚠️ prüft Benutzernamen auf Dating- und Erotikplattformen — Treffer sind Angaben über das **Sexualleben** einer Person (besonders schützenswert, DSG Art. 5 lit. c / DSGVO Art. 9) |

Änderung übernehmen:

```bash
docker compose up -d module-infra module-darknet module-dating
```

## Telegram, GHunt, KI

**Telegram.** Die schlüssellose Suche funktioniert ab Werk (öffentliche
Webvorschau). Die Tiefensuche (ganze Historie, Suche in Kanälen,
Übersetzung, Medien) braucht ein eigens dafür angelegtes Telegram-Konto:

1. https://my.telegram.org/apps → `api_id`, `api_hash`.
2. Einmalig interaktiv eine Session erzeugen (Telefon + Code):
   ```bash
   pip install telethon
   TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=abc… python3 scripts/telegram-session.py
   ```
3. Die drei Werte in `/glbadmin` → *Einstellungen* → Telegram eintragen
   (oder `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` in
   `.env`), dann
   `docker compose up -d --force-recreate module-messenger module-telegram`.

Die Kanalliste für die Benutzernamen-Suche ist
`modules/messenger/config/crime_channels.txt` (auch in der Konsole
bearbeitbar).

**GHunt** (Google-Konten) braucht eine Google-Session eines
*Wegwerf*-Kontos: `python3 scripts/ghunt-session.py` führt durch; den
ausgegebenen Master-Token in der Konsole eintragen (Einstellungen → Google).

**KI-Verknüpfung.** Vorgabe ist Gemini (Schlüssel in der Konsole). Für ein
lokales, souveränes Modell in `.env`: `AI_PROVIDER=local`,
`AI_LOCAL_BASE_URL=http://<ollama-host>:11434/v1`,
`AI_LOCAL_MODEL=llama3.1`, dann `docker compose up -d api n8n` und in n8n
(`/n8n/`) den Workflow *ai-link-local* aktivieren.

## Foren-Indizes

`threat_actor_check` und `linkbase_lookup` nutzen zwei Indizes, die aus
öffentlichen Fremdquellen zusammengestellt werden. Sie werden nicht
mitgeliefert; `setup.sh` startet den Download. Jederzeit aktualisieren in
der Konsole (Einstellungen → Indizes) oder:

```bash
docker compose exec module-forums curl -fsS -X POST localhost:8110/threat-actors/refresh
docker compose exec module-forums curl -fsS -X POST localhost:8110/linkbase/refresh
docker compose exec module-forums curl -fsS localhost:8110/threat-actors/status
```

## Geheimnisse — was sich nie ändern darf

`.env` enthält jedes Geheimnis. Manche dürfen rotiert werden, drei dürfen
nicht verändert werden:

| Variable | Bei Änderung |
|---|---|
| `APIKEY_KEK` | alle in der Konsole gespeicherten API-Schlüssel werden unlesbar. Nur mit `scripts/rekey-apikeys.py` rotieren (Anleitung in `.env.example`). |
| `LICENSE_KEK` | gespeicherte Kundengeheimnisse (SMTP-Passwort, Webhook-, IdP-Geheimnisse) werden unlesbar — es gibt keinen Weg zur Neuverschlüsselung. |
| `AUDIT_HMAC_KEY` | neue Audit-Einträge verketten sich nicht mehr mit den alten. |
| `POSTGRES_*_PASSWORD` | die Datenbank kennt noch das alte Passwort — zuerst in Postgres ändern. |

Keycloak-Client-Geheimnisse (`KEYCLOAK_CLIENT_SECRET`,
`PLATFORM_KC_CLIENT_SECRET`) dürfen geändert werden: `.env` anpassen,
`sudo ./setup.sh` erneut ausführen.

## Fehlerbehebung

| Symptom | Nachsehen |
|---|---|
| 502 auf einer Seite | `docker compose ps` — ein Container startet neu; `docker compose logs <dienst>` |
| Login kreist / „invalid redirect“ | die Browser-URL muss `https://PUBLIC_HOST[:PORT]` aus `.env` entsprechen; ändern mit `setup.sh --reconfigure` |
| „Organisation nicht registriert“ | E-Mail-Domain fehlt bei der Organisation (Konsole) |
| Ergebnisse fehlen | Speicher (`docker stats`, `dmesg \| grep -i oom`), API-Schlüssel fehlt (Hinweise zum Ergebnis), Ratenbegrenzung der Quelle |
| Frontend zeigt alte Version | die Adresse ist eingebaut: `docker compose build --no-cache frontend && docker compose up -d frontend` |
| Falldaten werden nicht gespeichert (All-in-one) | `docker compose exec api python -c "import httpx;print(httpx.get('http://data-agent-local:9000/health').text)"` und die Logs des Datenservers |
| Platte voll | `docker system df`; `docker builder prune` gibt den Build-Cache frei |
