# OOF — Open OSINT Framework

**Selbst gehostete OSINT-Ermittlungsplattform mit eingebauter Datenhoheit.**

[English](README.md) · [Installation](docs/install.de.md) · [Betrieb](docs/operations.de.md) · [Architektur (EN)](docs/architecture.md) · [Sicherheit](SECURITY.md)

**OOF** (Open OSINT Framework) bündelt rund 85 Open-Source-Intelligence-Werkzeuge hinter einer
Weboberfläche: Sie geben einen Selektor ein (E-Mail, Benutzername, Domain,
IP, Telefonnummer, Wallet, Firma …), OOF führt die passenden Werkzeuge
parallel aus, und die Funde landen in einem Fall als interaktiver Graph —
mit Quelle, Zeitpunkt und Bewertung für jede einzelne Angabe. Fälle lassen
sich auf Änderungen überwachen, exportieren (PDF/DOCX-Bericht, CSV,
Maltego, MISP, STIX) und innerhalb der Organisation teilen.

Der Grundsatz hinter allem: **Wer die Suchmaschine betreibt, bekommt die
Falldaten nicht.** Ermittlungsdaten liegen auf einem *Datenserver*, der der
nutzenden Organisation gehört — eigene Datenbank, eigenes
Benutzerverzeichnis. Auf einem einzelnen Server (all-in-one) laufen beide
einfach nebeneinander.

---

## Funktionen

| Bereich | Inhalt |
|---|---|
| **Suche** | 14 Module, ~85 Werkzeuge (drei heikle ab Werk aus): Benutzernamen (Sherlock, WhatsMyName …), E-Mail & Leaks (Holehe, HIBP, Hudson Rock, GHunt), Infrastruktur (DNS, crt.sh, Shodan, Passive DNS, subfinder, theHarvester), Threat Intel (VirusTotal, abuse.ch, OTX, GreyNoise, Ransomware-Tracker), Krypto (Etherscan, Blockscout, GoPlus), Darknet über Tor (Onion-Suche, Seiten lesen), Telegram/Discord, Foren, Firmen & Sanktionen (GLEIF, OpenSanctions, Schweizer Register), News/RSS |
| **Fälle** | Graph (Cytoscape), Herkunft je Fund, Bewertung nach Admiralty-Schema, Zusammenführen von Dubletten, eingeschränkte Fälle (Need-to-know), Beweissicherung (Screenshot + Hash) |
| **Überwachung** | geplante Wiederholungen, Änderungserkennung, Alarm per E-Mail oder Webhook |
| **Berichte & Export** | PDF/DOCX mit wählbaren Abschnitten, CSV, Maltego, MISP, STIX 2.1 |
| **KI-Verknüpfung** (optional) | schlägt Verbindungen vor, über Gemini oder ein lokales OpenAI-kompatibles Modell (Ollama/vLLM) |
| **Konten** | Keycloak (OIDC), TOTP, Rollen Admin/Ermittler/Leser, eigener IdP je Organisation im Mehrmandantenbetrieb |
| **Protokoll** | unveränderliches, HMAC-verkettetes Audit-Log mit externen Ankern; Selektoren optional nur als Hash |
| **Sprachen** | Oberfläche und Handbuch auf Deutsch, Englisch, Französisch, Italienisch |

Jeder API-Schlüssel ist optional. Werkzeuge ohne Schlüssel arbeiten
schlüssellos oder melden klar „Schlüssel nicht eingerichtet“, statt
abzubrechen.

## Zwei Installationsarten

```
 allinone  — ein Server                    operator — Framework für mehrere Organisationen
┌──────────────────────────────┐          ┌──────────────────────┐     ┌────────────────────┐
│ Framework (Web, API, Module, │          │ Framework            │ ──▶ │ Datenserver Org. A │
│ Login)                       │          │ (Web, API, Module,   │     │ DB + Keycloak + TLS│
│        │ internes Netz       │          │  Betreiberkonsole)   │     └────────────────────┘
│ Datenserver (Falldatenbank)  │          │                      │ ──▶ ┌────────────────────┐
└──────────────────────────────┘          └──────────────────────┘     │ Datenserver Org. B │
                                                                       └────────────────────┘
```

* **allinone** — eine Organisation, ein Team, eine Evaluation. Anmeldung
  über das Keycloak des Frameworks. Funktioniert mit IP-Adresse
  (selbstsigniertes Zertifikat) oder Domain (Let's Encrypt).
* **operator** — Sie betreiben das Framework für mehrere Organisationen;
  jede installiert mit `data-agent/install.sh` ihren eigenen Datenserver
  und behält eigene Benutzer und Falldaten. Sie halten beides nie.

## Schnellstart

Voraussetzungen: Debian 12 / Ubuntu 22.04+ (x86_64 oder arm64), 8 GB RAM,
2 CPU-Kerne, 40 GB Platte, root-Zugang. Docker installiert das Setup bei
Bedarf selbst.

```bash
git clone https://github.com/cybersecswiss/open-osint-framework.git /opt/oof
cd /opt/oof
sudo ./setup.sh
```

Das geführte Setup fragt Sprache, Installationsart, Adresse und einige
Namen ab, baut und startet alles (erster Lauf: 15–40 Minuten) und zeigt
am Ende, wo Sie sich anmelden. Die Zugangsdaten stehen danach in
`/root/oof-credentials.txt`.

Unbeaufsichtigt:

```bash
sudo ./setup.sh --lang de --mode allinone --host 203.0.113.10 \
     --admin-email admin@example.org --yes
```

Ausführliche Anleitung, alle Optionen, Fehlerbehebung:
**[docs/install.de.md](docs/install.de.md)**.

## Dokumentation

| Dokument | Für |
|---|---|
| [docs/install.de.md](docs/install.de.md) / [.en](docs/install.en.md) | Installation (beide Arten), Optionen, erste Anmeldung, Fehlerbehebung |
| [docs/customer-server.de.md](docs/customer-server.de.md) / [.en](docs/customer-server.en.md) | eine Organisation installiert ihren eigenen Datenserver (Betreibermodus) |
| [docs/operations.de.md](docs/operations.de.md) / [.en](docs/operations.en.md) | API-Schlüssel, Benutzer, Sicherung, Wiederherstellung, Updates, Telegram/GHunt, Logs |
| [docs/architecture.md](docs/architecture.md) | Aufbau: Container, Vertrauenszonen, Suchpfad, Modulvertrag (Englisch) |
| Handbuch in der App (`/handbook`) | Endnutzer — DE/EN/FR/IT |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Entwicklung, neues Modul, Tests (Englisch) |

## Verantwortungsvoller Einsatz

OOF ist ein Werkzeug für rechtmässige Ermittlungen: Sicherheitsforschung,
Betrugs- und Bedrohungsermittlung, Due Diligence, Journalismus,
Strafverfolgung im Rahmen ihres gesetzlichen Auftrags. Viele der
eingebundenen Quellen verarbeiten Personendaten. **Sie** sind dafür
verantwortlich, für jede Suche eine Rechtsgrundlage zu haben, die
Nutzungsbedingungen der aktivierten Quellen und API-Anbieter einzuhalten und
den Datenschutz (DSGVO / DSG oder Ihr lokales Recht) zu wahren. Die
Plattform hilft — Zweckfeld, Audit-Log, Need-to-know-Fälle,
Aufbewahrungsfristen —, aber sie macht eine Suche nicht rechtmässig. Siehe
[DISCLAIMER.md](DISCLAIMER.md).

## Kontakt

Fragen, Zusammenarbeit, kommerzielle Nutzung: **info@cybersecswiss.ch**
Sicherheitslücken: siehe [SECURITY.md](SECURITY.md) — bitte nicht als öffentliches Issue.

## Lizenz

Copyright © 2026 Aljoscha T. — siehe [NOTICE](NOTICE).

[GNU Affero General Public License v3.0](LICENSE). Wer eine veränderte
Fassung als Netzwerkdienst betreibt, muss deren Quellcode den Nutzern
anbieten. Fremdkomponenten und ihre Lizenzen: [THIRD_PARTY.md](THIRD_PARTY.md).
