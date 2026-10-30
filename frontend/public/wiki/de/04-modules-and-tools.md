# Module & Werkzeuge

Eine **Suche** lässt ein oder mehrere **Module** laufen. Jedes Modul bündelt
mehrere **Werkzeuge**, die echte OSINT-Quellen abfragen. Sie rufen Werkzeuge
nie direkt auf — Sie wählen einen **Abfragetyp**, geben einen Selektor ein und
kreuzen die gewünschten Module an. Das System führt automatisch jedes Werkzeug
aus, das diesen Abfragetyp versteht.

Es gibt **14 Module** (rund 85 Werkzeuge, drei davon ab Werk deaktiviert). Manche Werkzeuge benötigen einen von
Ihrem Betreiber hinterlegten API-Schlüssel; ohne ihn liefert nur dieses eine
Werkzeug den klaren Hinweis „Schlüssel nicht gesetzt", statt die Suche
scheitern zu lassen. Einige Module sind opt-in und erscheinen nur, wenn Ihre
Behörde dafür lizenziert ist.

| # | Modul | Wofür | Schlüssel nötig? |
|---|--------|---------------|--------------|
| 1 | **Alias-Pivot** (`alias`) | Einen Benutzernamen/Alias im Web finden | Nein |
| 2 | **Leaks & Datenlecks** (`leaks`) | E-Mail/Benutzername in Leaks + Kontospuren | Teilweise |
| 3 | **Infrastruktur** (`infra`) | Domain-/IP-Aufklärung, Phishing-Doppelgänger | Teilweise |
| 4 | **Threat Intel** (`threat`) | Reputation & Schadsoftware-Zuordnung eines IOC | Teilweise |
| 5 | **Darknet & Paste** (`darknet`) | Tor-Hidden-Services, Pastes, **Beschlagnahme-Wache** | Nein |
| 6 | **Messenger** (`messenger`) | Keylose Telegram-Vorschau, Discord, Telefon→Messenger | Teilweise |
| 7 | **Krypto-Verfolgung** (`crypto`) | Bitcoin-/Ethereum-Adressen + Wallet-Zuordnung | Teilweise |
| 8 | **Telegram (tief)** (`telegram`) | Authentifizierte, tiefe Telegram-Erhebung | Sitzung |
| 9 | **Compliance** (`compliance`) | Sanktions-/PEP-/Watchlist-Prüfung | Teilweise |
| 10 | **Kriminalitätsforen** (`forums`) | Forensuche, Akteursindex, PGP, Linkverzeichnisse | Teilweise |
| 11 | **Bild-OSINT** (`image`) | Foto-EXIF/GPS + KI-Ortsschätzung | Teilweise |
| 12 | **News & RSS** (`news`) | Volltextsuche über Behörden-, Polizei-, Medien- und Cyber-Feeds | Nein |
| 13 | **Firmen & Personen** (`corporate`) | Register, Konzernstruktur, Sanktionslisten, Verzeichnisse — siehe [eigene Seite](15-companies-and-people.md) | Nein |
| 14 | **Dating & Erotik** (`dating`) | Benutzernamen-Abgleich über Dating-/Erotikseiten — **ab Werk aus** | Nein |

---

## 1. Alias-Pivot — `alias`

Macht aus einem Benutzernamen oder Alias eine Karte von Konten.

| Werkzeug | Quelle | Hinweise |
|------|--------|-------|
| `sherlock` | 600+ Plattformen | Prüft, wo ein Benutzername existiert |
| `whatsmyname` | Live gepflegte Plattformliste | Stets aktuelle Abdeckung |
| `user_scanner` | Mehrere Seiten | Breiter Sweep nach Namenspräsenz |
| `linkook` | Graph verbundener Konten | Folgt Verweisen zwischen den Profilen einer Person |

**Abfragetyp:** `Benutzername / Alias`. Jeder Treffer wird nachverifiziert, um
Fehltreffer zu verwerfen — ein gelistetes Konto existiert also wirklich.

## 2. Leaks & Datenlecks — `leaks`

Wo eine E-Mail-Adresse bzw. ein Benutzername in Datenlecks aufgetaucht ist und
bei welchen Diensten er registriert ist.

| Werkzeug | Quelle | Schlüssel |
|------|--------|-----|
| `holehe` | ~120 Seiten | Nein — ist die Adresse dort registriert? |
| `hibp` | HaveIBeenPwned | Ja (`HIBP_API_KEY`) |
| `intelx` | Intelligence X | Nein — erzeugt einen Deep-Link |
| `ghunt` | Google-Konto | Sitzung — E-Mail/Gaia-ID → reiches Google-Profil, Maps-Bewertungen |
| `hudsonrock` | Infostealer-Intel | Keylos — E-Mail/Domain → Infostealer-Infektionen |

**Abfragetypen:** `E-Mail` (zusätzlich bei `hudsonrock` auch
Benutzername/Domain, bei `ghunt` auch eine Gaia-ID).

> **Passwörter** werden nur als SHA-256-Fingerabdruck plus maskierte Vorschau
> (`a••••z`) gespeichert, sofern Ihr Betreiber Klartext nicht ausdrücklich
> aktiviert.

## 3. Infrastruktur — `infra`

Domain- und IP-Aufklärung — und das Auffinden der **Phishing-/Doppelgänger**-
Infrastruktur rund um eine Marke.

| Werkzeug | Quelle | Schlüssel |
|------|--------|-----|
| `subfinder` | Subdomain-Aufzählung | Nein |
| `whois` | Registrierung / Inhaberschaft | Nein |
| `crtsh` | Certificate-Transparency-Logs | Nein |
| `dns_records` | A / AAAA / MX / NS / TXT / CNAME | Nein |
| `theharvester` | E-Mails/Hosts zu einer Domain | Nein |
| `shodan_host` | Offene Ports, Banner, CVEs | Ja (`SHODAN_API_KEY`) |
| `favicon_pivot` | Gleiches Favicon → verwandte Hosts | Ja (Shodan) |
| `dnstwist` | **Typosquat- / Phishing-Domains** | Nein |
| `passive_dns` | **Historische** Domain↔IP-Auflösungen (Mnemonic) | Nein |
| `asn_lookup` | Wer diese Adresse trägt: Präfix, AS, Halter (RIPEstat) | Nein |
| `origin_resolve` | Echter Server hinter einem CDN (Cloudflare & Co.), per Direktabfrage bestätigt — **ab Werk aus** (`ENABLE_ORIGIN_RESOLVE`) | Nein |

**Abfragetypen:** `Domain`, `IP-Adresse`, `URL`, `ASN`.

`dnstwist` macht aus einer Domain die Liste registrierter
Doppelgänger-Domains (Homoglyphen/IDN, Bitsquatting, TLD-Tausch …), die
tatsächlich auflösen — lebende Phishing-/Identitätsmissbrauchs-Kandidaten zum
Weiterpivotieren.

**`passive_dns` ist das Werkzeug, das zurückblickt.** Jedes andere hier
beantwortet „was ist jetzt wahr" — und genau diesen Zustand ändert ein
Betreiber, sobald er auffliegt. Passive DNS beantwortet „worauf zeigte diese
Domain im vergangenen März", und zwar in beide Richtungen; dort liegt meist
der Pivot. `asn_lookup` ergänzt einen neuen `asn`-Knoten, sodass Hosts
desselben Netzes im Graphen zusammenlaufen — das Muster kugelsicherer Hoster.

## 4. Threat Intel — `threat`

Reputation, Einstufung und **Schadsoftware-Zuordnung** eines Indikators.

| Werkzeug | Quelle | Schlüssel |
|------|--------|-----|
| `virustotal` | VirusTotal | Ja |
| `abuseipdb` | AbuseIPDB | Ja |
| `urlhaus` | abuse.ch URLhaus | Keylos/Schlüssel |
| `greynoise` | GreyNoise Community | Keylos |
| `urlscan` | urlscan.io | Keylos |
| `threatfox` | abuse.ch ThreatFox (IOC→Malware) | Schlüssel |
| `malwarebazaar` | abuse.ch MalwareBazaar (Hash→Sample) | Schlüssel |
| `ransomware_watch` | Leak-Site-Opfer, Gruppen, deren Onion-Seiten | Optional |
| `c2_intel` | Bekannte **Command-and-Control**-Infrastruktur aus Censys-Scans | Nein |
| `ioc_reputation` | **Wie viele unabhängige Blocklisten** diesen Indikator führen | Nein |
| `cve_lookup` | CVE-Details **plus** Ausnutzung in freier Wildbahn (NVD + CISA KEV) | Nein |

**Abfragetypen:** `Domain`, `IP-Adresse`, `URL`, `Hash`, `CVE`, `Stichwort`.

Drei davon versteht man am besten als Gruppe, weil sie verschiedene Fragen zur
selben Adresse beantworten:

* `c2_intel` — *wurde dieser Host als C2-Panel gesehen, und für welche
  Schadsoftware-Familie?* Ein Treffer ist eine Beobachtung der Software
  selbst, keine Meinung.
* `ioc_reputation` — *wie viele unabhängige Blocklisten führen ihn?* Eine
  einzelne Liste sagt wenig; Übereinstimmung zwischen Listen ohne gemeinsame
  Quelle sagt viel. Die Antwort nennt, wie viele Listen konsultiert wurden —
  eine kleine Zahl ist damit als Abdeckung lesbar und nicht als Unschuld.
* `cve_lookup` — *wird diese Schwachstelle tatsächlich ausgenutzt?* Ist der
  CISA-Katalog nicht erreichbar, gilt „ausgenutzt" als **unbekannt**, nie als
  „nein".

`ransomware_watch` läuft ohne Schlüssel, ist dann aber auf eine Abfrage pro
Minute und Endpunkt begrenzt; ein kostenloser Schlüssel von my.ransomware.live
hebt das auf, und das Werkzeug nutzt ihn von selbst.

## 5. Darknet & Paste — `darknet`

| Werkzeug | Abfragetyp | Was es tut |
|------|-----------|--------------|
| `ahmia` | `Stichwort` | Live-Suche in Tor-Hidden-Services (Torch/TorDex) |
| `paste_search` | `Stichwort` | Index von Paste-Seiten |
| `seizure_watch` | `Domain` (oder `.onion`) | **FBI-Watchdog:** erkennt eine behördliche **Beschlagnahme/Abschaltung** (Beschlagnahmebanner, Behördennamen) und sichert eine Momentaufnahme der Infrastruktur (A-/NS-Einträge, Weiterleitung), damit eine spätere Änderung auffällt |
| `onion_scrape` | `Onion-Adresse` | Ruft einen Hidden Service über Tor ab und extrahiert Kontakte/IOCs — **ab Werk aus** (`ENABLE_ONION_SCRAPE`) |

## 6. Messenger — `messenger`

Keyloses Telegram und Discord, dazu Telefon→Messenger.

| Werkzeug | Abfragetyp | Was es tut |
|------|-----------|--------------|
| `telegram_channel` | `Telegram-Kanal` | Vorschau eines öffentlichen Kanals |
| `tgstat` | `Telegram-Kanal` | Kanalstatistiken/-analysen |
| `telegram_username_hunt` | `Benutzername` | Durchsucht bekannte Kriminalitätskanäle nach dem Alias |
| `telegram_search` / `telegram_global_search` | `Telegram-Suche` | Öffentliche Telegram-Suchmaschinen |
| `telegram_message_search` | `Telegram-Nachrichtensuche` | Stichwort über die öffentliche Vorschau |
| `discord_invite` | `Discord-Einladung` | Löst eine Einladung auf → Serverinformationen |
| `discord_snowflake` | `Discord-ID` | Dekodiert eine Nutzer-ID → **Kontoerstellungsdatum** (keylos) |
| `discord_deep` | `Discord-ID` | **Vollständiges öffentliches Profil** (Name, Avatar/Banner, Abzeichen) — benötigt `DISCORD_BOT_TOKEN` |
| `phone_messenger` | `Telefon` | Normalisiert eine Nummer (Land/Anbieter/Anschlussart) + einen **WhatsApp-Deep-Link** zur manuellen Prüfung |

> `phone_messenger` behauptet nie, eine Nummer „sei bei WhatsApp" — es gibt
> keine regelkonforme automatische Prüfung. Es liefert Ihnen die geprüften
> Nummerndetails und einen Link, den Sie selbst öffnen.

## 7. Krypto-Verfolgung — `crypto`

| Werkzeug | Quelle | Schlüssel |
|------|--------|-----|
| `blockchain_btc` | blockchain.info | Keylos |
| `etherscan_eth` | Etherscan | Ja (`ETHERSCAN_API_KEY`) |
| `blockscout` | Blockscout (keylose ETH-Alternative) | Keylos |
| `wallet_attribution` | MistTrack | Ja — Wallet → Börse/Mixer/Betrug/Ransomware-Cluster + Risiko |

**Abfragetypen:** `Bitcoin-Adresse`, `Ethereum-Adresse`.

## 8. Telegram (tief) — `telegram`

Authentifizierte MTProto-Erhebung — vollständige Historie, Mitglieder sowie
Nutzer-, Telefon- und Geo-Abfragen. Benötigt eine von Ihrem Betreiber
eingerichtete Telegram-**Sitzung**. Eigene Seite:
**[Telegram-Werkzeuge](05-telegram.md)**.

## 9. Compliance — `compliance`

| Werkzeug | Quelle | Schlüssel |
|------|--------|-----|
| `opensanctions` | OpenSanctions (OFAC/EU/UN/SECO…) | Ja, oder keylos selbst betrieben |

Prüft einen **Namen, ein Unternehmen oder eine Krypto-Wallet** gegen
Sanktions-, PEP- und Beobachtungslisten. **Abfragetypen:** `Stichwort`/Name,
Krypto-Adresse.

## 10. Kriminalitätsforen — `forums`

| Werkzeug | Was es tut | Schlüssel |
|------|--------------|-----|
| `crime_forum_hunt` | Durchsucht Clearnet- und Darknet-Kriminalitätsforen nach Begriff/Alias/Kontakt-ID | Brave-Schlüssel hilft |
| `threat_actor_check` | Schlägt einen Alias in einem grossen Akteursindex nach | Keylos |
| `linkbase_lookup` | Abfrage eines kuratierten Darknet-Linkverzeichnisses | Keylos |
| `pgp_lookup` | Findet/parst den PGP-Schlüssel eines Akteurs samt Fingerabdruck | Keylos |

**Abfragetypen:** `Stichwort`, `Benutzername` sowie Kontakt-IDs (`Jabber`,
`Tox`, `Session`, PGP-Fingerabdruck).

## 11. Bild-OSINT — `image`

Ortsbelege aus einem Foto ziehen. **Abfragetyp:** `Bild-URL`.

| Werkzeug | Was es tut | Schlüssel |
|------|--------------|-----|
| `exif_gps` | Liest eingebettete EXIF-Daten: Kameramarke/-modell, Zeitstempel und **GPS** → ein `location`-Knoten mit Ortsnamen | Nein |
| `visual_geolocate` | Fehlt GPS, **schätzt eine KI den Ort** aus sichtbaren Hinweisen (Schilder, Architektur) — klar als *KI-Schätzung* gekennzeichnet, eine zu prüfende Spur | Ja (Gemini) |

> Die KI-Schätzung ist eine Spur, kein Beweis. Kann das Modell es nicht sagen,
> sagt es das und fügt nichts hinzu — es erfindet nie einen Ort.

## 12. News & RSS — `news`

| Werkzeug | Abfragetyp | Was es tut |
|------|-----------|--------------|
| `news_search` | `Stichwort` | Volltextsuche über die von Ihrem Betreiber gepflegten Feeds — Bundesstellen, Polizei, Medien, Technik und Cyber |

Jeder Treffer trägt **Datum, Quelle und Quellenart**. Eine Behördenmeldung und
ein Zeitungsartikel sind beide legitime Spuren, tragen aber nicht dasselbe
Beweisgewicht — deshalb erhalten amtliche Quellen zudem eine höhere
Confidence. Siehe [Eine Suche durchführen](03-searching.md#news--rss).

---

Weiter: **[Telegram-Werkzeuge →](05-telegram.md)** · Zurück: **[Eine Suche durchführen](03-searching.md)**

## 14. Dating & Erotik — `dating`

**Ab Werk deaktiviert.** Der Betreiber schaltet es bewusst mit
`ENABLE_DATING_SEARCH=true` ein; bis dahin bietet das Modul kein Werkzeug an.
Gedacht für konkrete Hinweise wie Sextortion, Romance Scam oder Menschenhandel.

> ⚠️ Ob jemand ein Profil auf einer Dating- oder Erotikplattform hat, ist
> eine Angabe über sein Sexualleben — besonders schützenswerte Personendaten.
> Nur mit konkreter Rechtsgrundlage und Zweck suchen und solche Fälle
> eingeschränkt führen.

| Werkzeug | Abfragetyp | Was es tut |
|----------|-----------|------------|
| `cupidcrawl` | `Benutzername` | Durchsucht rund 50 Dating-/Erotikplattformen nach dem Benutzernamen; jeder Treffer wird gegen eine Negativkontrolle verifiziert |

