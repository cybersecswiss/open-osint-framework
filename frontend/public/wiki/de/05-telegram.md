# Telegram-Werkzeuge (tief)

Das Modul **Telegram (tief)** führt *authentifizierte* Telegram-Erhebung über
die offizielle MTProto-Schnittstelle durch. Es liest deutlich mehr als die
öffentliche Web-Vorschau: vollständige Nachrichtenhistorie, Kanalmitglieder und
Administratoren, Weiterleitungen, Medien sowie Nutzer-, Telefonnummern- und
Geo-Abfragen.

> **Verfügbarkeit.** Dieses Modul arbeitet nur, wenn Ihr Betreiber eine aktive
> Telegram-Sitzung hinterlegt hat. Ist sie inaktiv, liefert jedes Werkzeug den
> klaren Hinweis *„telegram module not authenticated"* in den Ergebnissen,
> statt die ganze Suche scheitern zu lassen. Bitten Sie Ihren Betreiber um
> (erneute) Authentifizierung — siehe Betreiberhandbuch, *„Telegram deep
> scanner (module-telegram)"*.

## Die sechs Werkzeuge

| Werkzeug | Abfragetyp | Abfrage eingeben als … |
|------|-----------|---------------------|
| `telegram_scan` | `Telegram-Kanal` | `@kanal`, ein `t.me/…`-Link oder `+inviteHash` (mehrere durch Komma trennen) |
| `telegram_channel_info` | `Telegram-Kanal` | `@kanal` (mehrere durch Komma trennen) |
| `telegram_search` | `Telegram-Kanalsuche` | `@kan1,@kan2 :: stichwort` |
| `telegram_user_lookup` | `Telegram-Nutzer / ID` | `@nutzer` oder eine numerische ID (mehrere durch Komma trennen) |
| `telegram_phone_lookup` | `Telefonnummer` | E.164-Nummern, z. B. `+41790000000` (mehrere durch Komma trennen) |
| `telegram_geo` | `Telegram-Geo (lat,long)` | `47.3769,8.5417` |

Da `telegram_scan` und `telegram_channel_info` beide den Abfragetyp
`Telegram-Kanal` bedienen, laufen bei Auswahl des Moduls für eine Kanalabfrage
**beide** — Sie erhalten den vollständigen Scan *und* die Kanal-Metadaten.

## Was die einzelnen Werkzeuge liefern

**`telegram_scan`** — das Kernstück. Je Kanal/Gruppe/Einladung:
- den **Kanal** (Titel, Beschreibung, Mitgliederzahl, Verifiziert-Kennzeichen)
- **Nachrichten** (Text, Datum, Aufrufe, Weiterleitungen, Antworten,
  Reaktionen, Geodaten)
- **Mitglieder** und auf Wunsch **Administratoren** mit ihren Rollen
- **angeheftete** Nachrichten
- **Medien** (Dateiname, Grösse; optional SHA-256 / perzeptueller Hash / EXIF)
- **IOCs** aus dem Nachrichtentext (Krypto-Adressen, E-Mails, URLs,
  Telefonnummern, @Erwähnungen, #Hashtags, `t.me/`-Links)
- **Weiterleitungsquellen** als verknüpfte Kanäle

Daraus entsteht ein zusammenhängender Graph: Nachrichten *in* dem Kanal,
Verfasser, die sie *gepostet* haben, Mitglieder *des* Kanals, *erwähnte* IOCs,
*angehängte* Medien und Weiterleitungen *aus* anderen Kanälen.

**`telegram_channel_info`** — vollständige Kanal-Metadaten (Beschreibung,
Online-Zahl, verknüpfte Diskussionsgruppe, Slow-Modus, ob Teilnehmende
einsehbar sind) sowie **ähnliche/empfohlene Kanäle**.

**`telegram_search`** — serverseitige Stichwortsuche über die von Ihnen
genannten Kanäle. Syntax: Kanäle links von `::`, das Stichwort rechts:
`@ransomwatch,@leakchannel :: bitcoin`.

**`telegram_user_lookup`** — vollständiges Nutzerprofil: Bio, Online-Status /
zuletzt gesehen, Bot-/Scam-/Fake-/Verifiziert-/Premium-Kennzeichen sowie
**gemeinsame Chats** mit der Zielperson (bezogen auf das Erhebungskonto).

**`telegram_phone_lookup`** — prüft, ob eine Telefonnummer bei Telegram
registriert ist, und löst gegebenenfalls das Konto auf. Stark
ratenbegrenzt — für Einzelabfragen gedacht, nicht für Massenlisten.
Importierte Kontakte werden anschliessend automatisch gelöscht.

**`telegram_geo`** — findet Nutzer/Kanäle in der Nähe einer Koordinate, die
Geo-Sichtbarkeit aktiviert haben, samt Entfernung in Metern.

## Betriebshinweise

- **Ein Scan kann gross werden.** Mitglieder sind von Telegram auf rund
  10 000 begrenzt; die Nachrichtenzahl je Kanal folgt der vom Betreiber
  eingestellten Grenze.
- **Private / nur auf Einladung zugängliche Kanäle** benötigen `auto_join`
  (eine Betreiberoption) — sonst erhalten Sie nur Metadaten, sauber vermerkt.
- **Privatsphäre-Einstellungen** der Zielperson können Telefonnummer, „zuletzt
  gesehen" und Profilbilder verbergen; diese Felder erscheinen dann schlicht
  nicht.
- **Beweissicherung.** Jeder Telegram-Lauf wird in ein manipulationssicheres,
  hash-verkettetes Audit-Protokoll geschrieben (betreiberseitig) und hält
  fest, wer wann was erhoben hat.
- **Datenschutz (CH-Strafverfolgung).** Nachrichtentext und, bei aktivem
  Hashing, Medien werden unverändert erhoben. Halten Sie Scans auf das
  begrenzt, was der Fall benötigt.

---

Weiter: **[Den Graphen lesen →](06-reading-the-graph.md)** · Zurück: **[Module & Werkzeuge](04-modules-and-tools.md)**
