# Überwachung & Alarme

Eine Überwachung **wiederholt die Suche nach einer Entität in festem Abstand**
und meldet als Alarm, was seit dem letzten Lauf hinzugekommen ist.

## Überwachung anlegen

**Empfohlen:** im Fall die Entität öffnen (Knotenkarte oder Rechtsklick im
Graphen) → **„Monitoring aktivieren"**. Der Dialog ist mit der Entität
vorbelegt. **Alternativ:** **Monitoring** → **„Neues Monitoring"**, dann Fall
und Entität wählen.

Im Dialog:

- **Zweck / Rechtsgrundlage** — warum dieser Suchbegriff überwacht wird;
  Pflicht, wenn Ihre Behörde es verlangt (siehe
  [Eine Suche durchführen](03-searching.md)).
- **Intervall** — *Stündlich*, *Täglich* (Standard), *Wöchentlich* oder
  *Monatlich*.
- **„Alert bei"** — *Neuer Fund im Fall*, *Neues Konto, Profil oder Kennung*,
  *Neue Verbindung der überwachten Entität*. Keine Auswahl = alle Änderungen.
- **Alarm-E-Mail / Webhook** — optional je Überwachung; den Kanal für die
  ganze Behörde richtet die Administration unter **Admin → Alarmierung** ein.

Der **erste Lauf ist absichtlich still**: er hält fest, was schon da ist,
damit nur gemeldet wird, was danach dazukommt.

## Alarme

Neue Alarme erscheinen auf dem **Dashboard** („Ungelesene Alarme") und auf
der Seite **Alarme** über alle Fälle: ungelesene zuerst, mehrere auswählen und
als gelesen markieren, **„Fall öffnen"** springt direkt zum Fund. Hat Ihre
Administration E-Mail oder Webhook eingerichtet, werden Alarme auch dorthin
zugestellt.

Angeboten werden nur Änderungen, die die Plattform wirklich erkennen kann.
Sie bewahrt keine früheren Profilstände auf und kann ein gelöschtes Profil
nicht von einer gescheiterten Abfrage unterscheiden — „Profil geändert" oder
„Account gelöscht" gibt es deshalb nicht als Auslöser. Ältere Überwachungen,
die sie noch nutzten, zeigen einen Hinweis und laufen mit den übrigen weiter.

## Überwachungen verwalten

Die Liste **Monitoring** zeigt je Überwachung Entität, Intervall, Status und
nächsten Lauf. **„Konfigurieren"** öffnet sie: **Aktiv / Inaktiv** schalten,
Intervall, Auslöser und Zustellung ändern, dann **„Speichern"**. Automatische
Nachsuchen stehen im **„Suchprotokoll"** des Falls.

---

Weiter: **[Berichte →](08-reports.md)** · Zurück: **[Den Graphen lesen](06-reading-the-graph.md)**
