# OOF installieren

[English](install.en.md) · zurück zum [README](../README.de.md)

Diese Anleitung führt von einem leeren Server zu einer laufenden
Installation. Die Arbeit macht das Setup-Skript; hier steht, was es fragt,
was es tut und was zu tun ist, wenn etwas schiefgeht.

---

## 1. Installationsart wählen

| | **allinone** | **operator** |
|---|---|---|
| Für wen | eine Organisation, ein Team, eine Evaluation | ein Anbieter für mehrere Organisationen |
| Falldaten | auf demselben Server, in einem eigenen Datenserver-Stack | auf dem eigenen Datenserver jeder Organisation |
| Benutzerkonten | im Keycloak des Frameworks | im eigenen Keycloak jeder Organisation |
| Adresse | IP-Adresse **oder** Domain | Domain empfohlen (die Server der Organisationen rufen sie auf) |
| Danach | anmelden und arbeiten | Organisationen in `/glbadmin` anlegen, diese installieren [ihren Datenserver](customer-server.de.md) |

Im Zweifel: **allinone**. Eine bestehende Installation lässt sich nicht
von einer Art in die andere umstellen; dafür neu installieren.

## 2. Voraussetzungen

| | Minimum | Hinweis |
|---|---|---|
| Betriebssystem | Debian 12, Ubuntu 22.04 / 24.04 | andere systemd-Linux-Systeme gehen vermutlich, sind aber ungetestet |
| CPU | 2 Kerne, x86_64 oder arm64 | mit 4 Kernen ist der erste Build doppelt so schnell |
| RAM | 8 GB | ~30 Container; unter 8 GB werden Werkzeuge unter Last beendet |
| Platte | 40 GB frei | Images ~15 GB, dazu Daten und Sicherungen |
| Netz | Internetzugang ausgehend | für den Build und die OSINT-Quellen |
| Ports | 443 und 80 (oder zwei freie Ausweichports) | das Setup bietet Ausweichports an, wenn sie belegt sind |
| Zugang | root (`sudo`) | |

Docker und Docker Compose installiert das Setup bei Bedarf selbst.

Einen Server prüfen, ohne etwas zu verändern:

```bash
./setup.sh --check
```

### Domain und Zertifikat

* **IP-Adresse** → es wird ein selbstsigniertes Zertifikat erzeugt. Browser
  warnen einmal; die Warnung akzeptieren. Gut für internen Einsatz und
  Evaluation.
* **Domain** → das Setup kann ein kostenloses **Let's-Encrypt**-Zertifikat
  beziehen. Vorher einen DNS-`A`-Eintrag auf den Server setzen und
  sicherstellen, dass Port **80** aus dem Internet erreichbar ist
  (HTTP-01-Challenge). Das Zertifikat erneuert sich selbst.

## 3. Installieren

```bash
sudo apt-get install -y git          # falls git fehlt
sudo git clone https://github.com/cybersecswiss/open-osint-framework.git /opt/oof
cd /opt/oof
sudo ./setup.sh
```

Das Setup läuft durch zwölf nummerierte Schritte:

| Schritt | Was passiert |
|---|---|
| 1 Voraussetzungen | Speicher, CPU, Platte, Internet, Architektur |
| 2 Angaben | Art, Adresse, Zertifikat, Ports, Namen (siehe unten) |
| 3 System | Pakete (curl, git, jq, openssl, python3, cron), Docker falls nötig |
| 4 Firewall | optional `ufw`: nur SSH und die zwei Web-Ports offen |
| 5 Konfiguration | `.env` mit ~20 erzeugten Geheimnissen (`chmod 600`) |
| 6 Zertifikat | selbstsigniert, oder ein Übergangszertifikat für Let's Encrypt |
| 7 Bauen & starten | baut ~20 Images und startet den Stack (beim ersten Mal **15–40 Min.**) |
| 8 Let's Encrypt | bezieht das echte Zertifikat + Erneuerung (nur Domain) |
| 9 Login | Keycloak-Realms `osint` (Benutzer) und `platform` (Betreiberkonsole) |
| 10 Organisation | allinone: legt Ihre Organisation, den ersten Benutzer und den lokalen Datenserver an |
| 11 Datensätze / Release | lädt zwei Foren-Indizes im Hintergrund; operator: veröffentlicht das Datenserver-Release unter `/agent/` |
| 12 Prüfung | prüft jeden Teil und schreibt die Zugangsdaten-Datei |

### Die Fragen

| Frage | Bedeutung |
|---|---|
| Sprache | Sprache der Setup-Ausgabe (`en`/`de`) |
| Installationsart | `allinone` oder `operator` (Abschnitt 1) |
| Öffentliche Adresse | was Benutzer im Browser eingeben: IP oder DNS-Name. Wird erkannt. |
| Let's Encrypt? | nur bei einer Domain |
| HTTPS-Port | nur wenn 443 belegt ist (z. B. durch einen anderen Webserver); Vorschlag 8443 |
| E-Mail des Betreibers | Meldungen von Let's Encrypt; beim selbstsignierten Zertifikat optional |
| Login des Product Owners | Benutzername für die Betreiberkonsole `/glbadmin` (Vorgabe `owner`) |
| *nur allinone:* Organisations-ID | kurze ID in Kleinbuchstaben, z. B. `main` |
| *nur allinone:* erster Benutzer + E-Mail | Ihr Administrator. **Benutzer melden sich mit ihrer E-Mail-Adresse an**; deren Domain bestimmt die Organisation. |
| *nur allinone:* E-Mail-Domains | alle Domains der Adressen Ihrer Benutzer, durch Komma getrennt |

### Unbeaufsichtigte Installation

Für jede Frage gibt es eine Option; `--yes` übernimmt für den Rest die
Vorgaben:

```bash
sudo ./setup.sh --lang de --mode allinone --host osint.example.org \
     --tls letsencrypt --email ops@example.org \
     --admin-email alice@example.org --email-domains example.org --yes
```

| Option | |
|---|---|
| `--lang en\|de` | Sprache |
| `--mode allinone\|operator` | Installationsart |
| `--host NAME\|IP` | öffentliche Adresse |
| `--tls selfsigned\|letsencrypt` | Zertifikatsart |
| `--http-port N`, `--https-port N` | Ports (Vorgabe 80/443) |
| `--email ADR` | Kontakt des Betreibers |
| `--owner-user NAME` | Login des Product Owners (Vorgabe `owner`) |
| `--tenant ID`, `--admin-user NAME`, `--admin-email ADR`, `--email-domains LISTE` | allinone: Organisation und erster Benutzer |
| `--no-firewall` | Firewall nicht anfassen |
| `--skip-datasets` | Foren-Indizes nicht laden |
| `--skip-release` | operator: Datenserver-Release nicht veröffentlichen |
| `--reconfigure` | beim erneuten Lauf Adresse, Ports und Zertifikat neu abfragen |
| `--check` | nur den Server prüfen |
| `--yes` | unbeaufsichtigt |

## 4. Erste Anmeldung

Das Setup endet mit den Adressen und schreibt alle Zugangsdaten nach
**`/root/oof-credentials.txt`** (nur für root lesbar):

```bash
sudo cat /root/oof-credentials.txt
```

* **Webanwendung** `https://<adresse>/` — *allinone*: mit der
  **E-Mail-Adresse** des ersten Benutzers und dem erzeugten Passwort
  anmelden. Bei der ersten Anmeldung wählen Sie ein eigenes Passwort und
  richten eine Authenticator-App ein (TOTP, z. B. Aegis, Google
  Authenticator, 1Password).
* **Betreiberkonsole** `https://<adresse>/glbadmin` — Konto des Product
  Owners: API-Schlüssel, Organisationen, Lizenzen, News-Feeds, Forenlisten.
* **Keycloak-Verwaltung** `https://<adresse>/auth/admin/` — nur für
  Sonderfälle; Benutzer werden normalerweise in der App verwaltet
  (Admin → Benutzerverwaltung).
* **Grafana** `https://<adresse>/grafana/` — Container-Metriken.

Übernehmen Sie die Zugangsdaten in einen Passwort-Manager und löschen Sie
die Datei.

## 5. Direkt nach der Installation

1. **API-Schlüssel** (optional) — `/glbadmin` → *Einstellungen*. Jeder
   Schlüssel hat einen *Test*-Knopf. Am besten mit den kostenlosen
   beginnen: abuse.ch, AlienVault OTX, VirusTotal, AbuseIPDB, Etherscan.
   Details: [Betrieb](operations.de.md#api-schlüssel).
2. **Benutzer** — in der App: *Admin → Benutzerverwaltung → Neuer Benutzer*. Deren
   E-Mail-Domain muss zu den Domains der Organisation gehören
   (Betreiberkonsole → Organisation → E-Mail-Domains).
3. **Sicherung** — [Betrieb → Sicherung](operations.de.md#sicherung). Ohne
   Kopie an einem anderen Ort verliert ein Plattendefekt jeden Fall.
4. **Betreibermodus** — die erste Organisation anlegen und deren IT die
   [Datenserver-Anleitung](customer-server.de.md) schicken.

## 6. Aktualisieren, erneut ausführen, Adresse ändern

```bash
cd /opt/oof
sudo git pull
sudo ./setup.sh          # repariert + aktualisiert; Geheimnisse und Daten bleiben
```

Neue Adresse oder Ports (z. B. Domain statt IP):

```bash
sudo ./setup.sh --reconfigure
```

Dabei wird bei Bedarf das Zertifikat neu erzeugt und das Web-Frontend neu
gebaut, in das die Adresse eingebaut ist.

## 7. Fehlerbehebung

| Symptom | Ursache / Lösung |
|---|---|
| Setup bricht in Schritt 7 (Build) ab | vollständiges Log: `/var/log/oof-build.log`. Meist ein Netzaussetzer beim Download — einfach `sudo ./setup.sh` erneut starten; fertige Images werden weiterverwendet. |
| „Port … ist belegt“ | ein anderer Webserver nutzt ihn. Freigeben, oder bei der Port-Frage einen freien Port angeben (`--https-port 8443 --http-port 8080`). |
| Let's Encrypt fehlgeschlagen | DNS zeigt noch nicht auf den Server, oder Port 80 ist durch eine Cloud-Firewall gesperrt. Beheben und erneut starten; das Übergangszertifikat funktioniert so lange weiter. Log: `/var/log/oof-certbot.log`. |
| Browser: „Verbindung nicht privat“ | beim selbstsignierten Zertifikat erwartet — einmal akzeptieren. |
| Login-Seite kreist / „invalid redirect“ | die Adresse im Browser weicht von der eingerichteten ab (IP statt Name, Port fehlt). Genau die vom Setup ausgegebene URL verwenden oder mit `--reconfigure` ändern. |
| „Ihre Organisation ist nicht registriert“ | die E-Mail-Domain ist keiner Organisation zugeordnet. Betreiberkonsole → Organisation → E-Mail-Domains. |
| 502 Bad Gateway auf einer Seite | ein Container startet (neu). `docker compose ps`; 30 s warten; `docker compose logs <dienst>`. |
| Suchen liefern weniger als erwartet | Speichermangel (`docker stats`, `dmesg \| grep -i oom`), oder das Werkzeug braucht einen API-Schlüssel (steht in den Hinweisen zum Ergebnis). |
| Keycloak-Einrichtung fehlgeschlagen (Schritt 9) | `/var/log/oof-keycloak.log`; Keycloak braucht beim ersten Start ~2 Min. — Setup erneut starten. |

Zustandsübersicht jederzeit:

```bash
cd /opt/oof && bash scripts/health-check.sh
```

## 8. Deinstallieren

```bash
cd /opt/oof
docker compose down                       # anhalten, Daten bleiben
(cd data-agent && docker compose -f docker-compose.yml -f docker-compose.local.yml down)
# Löscht ALLE Daten unwiderruflich — Fälle, Benutzer, Einstellungen:
docker compose down -v
(cd data-agent && docker compose -f docker-compose.yml -f docker-compose.local.yml down -v)
```
