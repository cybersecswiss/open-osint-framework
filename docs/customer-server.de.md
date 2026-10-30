# Den eigenen Datenserver einrichten (Betreibermodus)

[English](customer-server.en.md) · zurück zum [README](../README.de.md)

**Für die IT einer Organisation, die ein von jemand anderem betriebenes
OOF-Framework nutzt (den *Betreiber*). Bitte vor Beginn ganz lesen.**

> Sie betreiben OOF für sich selbst auf einem Server? Dann brauchen
> Sie diese Seite **nicht** — verwenden Sie `setup.sh --mode allinone`
> ([Installationsanleitung](install.de.md)).

---

## 1. Worum es geht

Sie richten einen Server ein, auf dem **Ihre Ermittlungsdaten liegen — und
nur dort**. Der Betreiber stellt das Such-Framework; Fälle, Entitäten und
Beziehungen werden ausschliesslich auf diesem Server gespeichert, in Ihrer
eigenen Datenbank, hinter Ihrem eigenen Login-Dienst (Keycloak).

> **Der Betreiber hat keinen administrativen Zugang zu diesem Server und
> keine Kopie Ihrer Passwörter.** Niemand ausser Ihnen kann ein Passwort
> zurücksetzen oder gelöschte Fallakten wiederherstellen.

## 2. Was Sie vorbereiten

| | Anforderung | Hinweis |
|---|---|---|
| Server | Debian 12 oder Ubuntu 22.04/24.04, frisch | x86_64 |
| Speicher / Platte | 4 GB / 20 GB frei | 8 GB empfohlen |
| Zugang | root oder `sudo` | |
| Adresse | ein **DNS-Name**, der hierher zeigt (empfohlen) **oder** eine IP-Adresse | siehe unten |
| Ports | 443 (und 80 für Let's Encrypt) für Framework und Benutzer erreichbar | andere Ports möglich |
| Vom Betreiber | **Framework-Adresse** (z. B. `https://osint.example.org`) und **Lizenzschlüssel** | |
| E-Mail | für Zertifikatsmeldungen und den ersten Administrator | |

### DNS-Name oder IP-Adresse?

* **DNS-Name + Let's Encrypt** (empfohlen für alles, was über das Internet
  erreichbar ist): zuerst den `A`-Eintrag anlegen und prüfen:
  `dig +short daten.example.org` muss die IP dieses Servers ausgeben.
  Port 80 muss für die Zertifikats-Challenge aus dem Internet erreichbar sein.
* **IP-Adresse oder interner Name** (LAN, Test): der Datenserver erhält ein
  **selbstsigniertes** Zertifikat. Der Betreiber muss dann im Framework
  `TLS_VERIFY_AGENT=false` und `TLS_VERIFY_IDP=false` setzen, und die
  Browser Ihrer Benutzer warnen einmal auf der Login-Seite.

## 3. Installation

```bash
curl -fsSL https://<framework-adresse>/agent/install.sh -o install.sh
sudo bash install.sh
```

Verwendet das **Framework** ein selbstsigniertes Zertifikat, mit
`curl -fsSLk …` herunterladen und die Rückfrage des Installers mit *ja*
beantworten — nur wenn der Betreiber das so mitgeteilt hat.

Der Installer fragt zuerst die Sprache ab und führt dann durch zehn
Schritte:

| Schritt | Was passiert |
|---|---|
| 1 Voraussetzungen | Speicher, Platte, Internet |
| 2 Bestehende Installation | ein erneuter Lauf repariert; Passwörter werden nie neu erzeugt |
| 3 Angaben | Framework-Adresse, Lizenzschlüssel, Adresse dieses Servers, Zertifikatsart, Ports, E-Mail, erster Administrator |
| 4 Lizenz | beim Framework geprüft; Ihr Zugriffsschlüssel wird abgerufen |
| 5 System | Docker wird bei Bedarf installiert |
| 6 Programmdateien | geladen und **gegen die Release-Prüfsummen geprüft** |
| 7 Konfiguration | Passwörter erzeugt, Login-Realm vorbereitet |
| 8 Dienste | Datenbank, Datenserver, Keycloak, TLS-Proxy (Caddy) |
| 9 Sicherung | täglich 02:15, 30 werden behalten |
| 10 Prüfung | einschliesslich HTTPS |

Dauer: 5–15 Minuten.

Unbeaufsichtigt:

```bash
sudo bash install.sh --lang de --framework-url https://osint.example.org \
     --license-key '<SCHLÜSSEL>' --host daten.example.org --tls letsencrypt \
     --email it@example.org --admin-email admin@example.org --yes
```

Weitere Optionen: `--tls internal` (selbstsigniert), `--https-port 8443`,
`--http-port 8080`, `--admin-user NAME`, `--insecure-framework`,
`--install-dir VERZ` — `bash install.sh --help`.

## 4. Danach

### 4.1 Dem Betreiber drei Angaben senden

```
Datenserver:  https://daten.example.org
Login:        https://daten.example.org/auth/realms/<mandant>
Mandant:      <mandant>
```

Sie enthalten kein Geheimnis. Der Betreiber trägt sie in der Konsole ein;
erst dann können sich Ihre Benutzer anmelden.

### 4.2 Zugangsdaten sichern

```bash
sudo cat /root/oof-agent-credentials.txt
```

* **Keycloak-Hauptadministrator** — verwaltet den Login-Dienst
* **Erster Administrator Ihrer Organisation** — legt die weiteren Konten an;
  muss das Passwort bei der ersten Anmeldung ändern

In den Passwort-Manager übernehmen und die Datei danach löschen.

### 4.3 Erste Anmeldung

1. Die Framework-Adresse im Browser öffnen.
2. Die dienstliche E-Mail-Adresse eingeben — Sie werden an **Ihren**
   Login-Dienst weitergeleitet.
3. Als erster Administrator anmelden.

Weitere Benutzer: in der App unter *Admin → Benutzerverwaltung*, oder in
Ihrem Keycloak unter `https://<ihre-adresse>/auth/admin/` → Realm
`<mandant>` → Users.

## 5. Betrieb

```bash
cd /opt/oof-agent
sudo docker compose ps              # läuft alles?
sudo docker compose logs -f agent   # Log mitlesen
sudo ./backup.sh                    # jetzt sichern
sudo ./update.sh --check            # gibt es ein Update?
sudo ./update.sh                    # einspielen
```

**Sicherungen** landen in `/opt/oof-agent/backups/` auf demselben
Server. Nur eine Kopie an einem anderen Ort schützt vor einem Plattendefekt
— nehmen Sie das Verzeichnis in Ihre bestehende Sicherung auf.

**Updates** — `update.sh` vergleicht die Versionen, sichert vorher, prüft
jede Datei gegen die Prüfsummen, startet die neue Version und **rollt
automatisch zurück**, wenn sie nicht gesund hochkommt. Falldaten werden
nicht angefasst. Automatisch, z. B. jeden Sonntag 03:00:

```bash
sudo crontab -e
0 3 * * 0 cd /opt/oof-agent && ./update.sh --yes >> /var/log/oof-update.log 2>&1
```

## 6. Fehlerbehebung

| Meldung / Symptom | Ursache und Abhilfe |
|---|---|
| „Das Framework ist nicht erreichbar“ | falsche Adresse, kein Internet, oder der Betreiber hat noch kein Release veröffentlicht (`bash scripts/release.sh` auf dem Framework). Test: `curl -I https://<framework>/agent/version.json` |
| „TLS-Zertifikat ist nicht vertrauenswürdig“ | das Framework nutzt ein selbstsigniertes Zertifikat. Nur akzeptieren, wenn der Betreiber es bestätigt hat (`--insecure-framework`). |
| „Lizenz ungültig“ | falscher Schlüssel, Lizenz abgelaufen oder deaktiviert — beim Betreiber nachfragen. |
| „Port … ist belegt“ | hier läuft schon ein Webserver. Stoppen, oder `--https-port`/`--tls internal` verwenden. |
| „https://… antwortet noch nicht“ | DNS zeigt noch nicht hierher, Port 80/443 vorgelagert gesperrt, Let's Encrypt arbeitet noch. `docker compose logs proxy` |
| „Prüfsumme stimmt nicht“ | eine Datei wurde unterwegs verändert oder das Release ist inkonsistent. **Abbrechen** und den Betreiber kontaktieren. |
| Anmeldung klappt nicht | der Betreiber hat Ihre Adressen noch nicht eingetragen — oder bei selbstsigniertem Zertifikat fehlt `TLS_VERIFY_IDP=false` im Framework. |

Für eine Störungsmeldung senden:

```bash
cd /opt/oof-agent
sudo docker compose ps
sudo docker compose logs --tail 100 agent
cat .installed-version.json
```

**Niemals `.env` oder Dateien aus `backups/` senden** — sie enthalten
Passwörter und Falldaten.

## 7. Entfernen

```bash
cd /opt/oof-agent
sudo ./backup.sh                # eine letzte Sicherung
sudo docker compose down        # anhalten (Daten bleiben)
sudo docker compose down -v     # ⚠ LÖSCHT ALLE DATEN UNWIDERRUFLICH
```
