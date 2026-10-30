# Referenz & Glossar

## Abfragetypen

Der **Abfragetyp** sagt der Plattform, wie sie Ihren Suchbegriff verstehen
soll und welche Module bzw. Werkzeuge ihn bearbeiten können. Sie wählen ihn im
Auswahlfeld *Typ* des Suchformulars.

| Abfragetyp (Auswahl) | Beispieleingabe | Üblicherweise bearbeitet von |
|-----------------------|---------------|----------------------|
| Benutzername / Alias | `anonymous99` | alias, leaks (hudsonrock), messenger (Username-Hunt) |
| E-Mail | `max@example.com` | leaks |
| Domain | `example.com` | infra, threat |
| IP-Adresse | `1.2.3.4` | infra, threat |
| URL | `http://bad.example/x` | threat |
| Hash (MD5/SHA1/SHA256) | `sha256:…` | threat |
| Telefonnummer | `+41790000000` | **telegram** |
| Bitcoin-Adresse | `bc1q…` | crypto |
| Ethereum-Adresse | `0x…` | crypto |
| CVE-Kennung | `CVE-2026-0257` | threat (`cve_lookup`) |
| ASN | `AS13335` | infra (`asn_lookup`) |
| Telegram-Kanal | `@durov` | messenger (keylos), **telegram** (tief) |
| Telegram-Kanalsuche | `ransomware` | messenger |
| Telegram-Nachrichtensuche | `@kanal :: stichwort` | messenger |
| Telegram-Nutzer / ID | `@nutzer` | **telegram** |
| Telegram-Geo (lat,long) | `47.3769,8.5417` | **telegram** |
| Discord-Einladung | `discord.gg/abc` | messenger |
| Bild-URL | `https://…/foto.jpg` | image |
| Stichwort (Darknet/Paste/News) | `acme breach` | darknet, forums, news |

Im Suchformular erscheinen nur Module als ankreuzbare Optionen, die den
gewählten Abfragetyp verstehen.

## Entitätstypen im Graphen

Knoten sind nach Typ eingefärbt. Unbekannte Typen werden grau dargestellt und
funktionieren trotzdem.

| Farbe | Entitätstyp | Bedeutung |
|:------:|-------------|---------|
| 🔵 | `person` | Eine Person |
| 🟢 | `social_account` | Ein Social-Media-Konto |
| 🟠 | `organization` | Eine Organisation |
| 🔴 | `email_address` | Eine E-Mail-Adresse |
| 🟣 | `domain` | Eine Domain |
| 🩵 | `username` | Ein Benutzername / Alias |
| 🩷 | `ip_address` | Eine IP-Adresse |
| 🟢 | `phone_number` | Eine Telefonnummer |
| 🟧 | `location` | Ein geografischer Ort |
| ⬜ | `asn` | Ein autonomes System (Netzbetreiber) |
| ⬜ | `malware` | Eine Schadsoftware- bzw. C2-Familie |
| ⬜ | `ransomware_group` / `ransomware_victim` | Leak-Site-Gruppe bzw. deren Opfer |
| ⬜ | `threat_source` | Eine Blocklisten-Quelle, die einen Indikator führt |
| 🔵 | `telegram_channel` | Ein Telegram-Kanal / eine Gruppe |
| 🔵 | `telegram_message` | Eine Telegram-Nachricht |
| 🔵 | `telegram_user` | Ein Telegram-Nutzer |
| 🔵 | `telegram_media` | Eine Mediendatei in Telegram |
| 🔴 | `telegram_ioc` | Ein in einer Nachricht gefundener Indikator (Krypto/E-Mail/URL/…) |
| 🟣 | `telegram_linked_channel` | Ein über eine Weiterleitung referenzierter Kanal |

## Kantenbeziehungen

Kanten sind mit der Beziehung beschriftet. Die Telegram-Erhebung erzeugt:

`POSTED` · `POSTED_IN` · `IN_CHANNEL` · `MEMBER_OF` · `ADMIN_OF` ·
`PINNED_IN` · `REPLY_TO` · `FORWARDED_FROM` · `MENTIONS` · `HAS_MEDIA` ·
`COMMON_CHAT` · `LINKED_DISCUSSION` · `SIMILAR_TO`

Andere Module ergänzen eigene (z. B. eine Alias-zu-Konto-Verbindung,
`hosts_c2_for` für C2-Infrastruktur oder `listed_by` für einen
Blocklisten-Eintrag). Fahren Sie im Graphen über eine Kante, um ihre
Beschriftung zu sehen.

## Aus Telegram-Text extrahierte Indikatortypen (IOC)

`btc` · `eth` · `xmr` · `ltc` · `tron` (Krypto-Adressen) · `email` ·
`url` · `telegram_link` · `phone` · `mention` (@Handle) · `hashtag`.

## Glossar

- **Fall** — der Behälter für eine Ermittlung. Jedes Suchergebnis hängt an
  einem Fall.
- **Entität** — ein Knoten im Fallgraphen (Person, Konto, Kanal, Adresse,
  Nachricht …).
- **Kante** — eine beschriftete Beziehung zwischen zwei Entitäten.
- **Modul** — ein eigenständiger Erheber (einer von 13). Sie wählen je Suche,
  welche laufen.
- **Werkzeug** — eine einzelne Quelle innerhalb eines Moduls (z. B.
  `virustotal`).
- **Abfragetyp** — wie Ihr Suchbegriff verstanden wird (siehe oben).
- **IOC** — Indicator of Compromise: eine Krypto-Adresse, E-Mail, URL, ein
  Hash usw.
- **Bewertung (Admiralty)** — Quellenzuverlässigkeit (A–F) und Glaubwürdigkeit
  der Aussage (1–6), siehe [Funde bewerten](12-assessing-findings.md).
- **Kreuzbestätigung** — wie viele unabhängige Werkzeuge denselben Fund
  gemeldet haben.
- **Platzhalter** — ein Knoten, der nur existiert, um den Graphen
  zusammenzuhalten; niemand hat ihn behauptet, er erscheint nie in Berichten.
- **Mandant** — Ihre Organisation. Ihre Daten liegen im Speicher Ihrer eigenen
  Organisation; der Plattformbetreiber kann sie nicht lesen.
- **Sitzung (Telegram)** — die authentifizierte Telegram-Anmeldung, die das
  tiefe Modul nutzt; von Ihrem Betreiber gepflegt.

## Fehlerbehebung

| Symptom | Bedeutung / was tun |
|---------|----------------------|
| Eine Werkzeugzeile zeigt „Schlüssel nicht gesetzt" | Diese Quelle braucht einen API-Schlüssel, den Ihr Betreiber nicht hinterlegt hat. Alle anderen Werkzeuge sind gelaufen. |
| Telegram-Werkzeuge melden „nicht authentifiziert" | Die Telegram-Sitzung ist inaktiv — bitten Sie Ihren Betreiber, sie neu zu authentifizieren. |
| Für meinen Abfragetyp erscheinen keine Module | Kein installiertes Modul bearbeitet diesen Typ; wählen Sie einen anderen Typ oder Begriff. |
| Ein Knoten wirkt unverbunden | Es ist der gesuchte Begriff (die „Wurzel") oder ein Endpunkt, zu dem kein Werkzeug vollständige Angaben geliefert hat. |
| Suche abgeschlossen, aber wenige Ergebnisse | Normal — ein sauberes Negativergebnis (etwa eine E-Mail-Adresse ohne Leaks) ist ein gültiges Resultat. |
| Ein Fund hat keine Belegstelle und keine Bewertung | Er stammt aus der Zeit vor der Provenienz-Erfassung. Ein erneuter Lauf füllt beides auf, ohne Dubletten zu erzeugen. |

## Einstellungen der Behörde (für Administratoren)

Unter **Admin → Einstellungen** legt die Administration Ihrer Behörde für alle
fest:

| Einstellung | Wirkung |
|---|---|
| Anzeige-Name, Logo | Kopfzeile und Deckblatt der Berichte |
| Standardsprache | Sprache der Oberfläche, bis jemand selbst eine wählt |
| Zweck bei jeder Suche verlangen | Suchen und neue Überwachungen brauchen einen Zweck / eine Rechtsgrundlage, festgehalten im Suchprotokoll |
| Klassifizierungsvermerk im Bericht | In Rot auf jeder Seite jedes PDF-Berichts |
| Standard-Playbook | In der Suche vorgewählt, wo es passt |
| Gesperrte Module | Lizenzierte Module, die Ihre Behörde nicht verwendet — weg aus der Suche und aus bestehenden Überwachungen |
| Session-Timeout, Auto-Löschen | Abmeldung nach Inaktivität; Löschung geschlossener Fälle nach N Monaten |

Module lassen sich hier nur **abschalten**; welche Module lizenziert sind, ist
Teil Ihres Vertrags mit dem Plattformbetreiber.

**Selbsttest.** *Admin → Selbsttest* prüft in einer Liste mit Ampel, ob Ihre
Installation funktioniert: Lizenz, Datenspeicher (erreichbar, Schlüssel
angenommen, aktuell), TLS-Zertifikat, Unversehrtheit der Protokollkette,
Anmeldedienst, Alarmkanal und Beweissicherung — jeweils mit einem Satz, was zu
tun ist. Nach jeder Installation und jedem Update ausführen.

---

Zurück: **[Startseite](00-overview.md)**
