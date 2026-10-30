# Mit Fällen arbeiten

Jede Ermittlung liegt in einem **Fall**. Alle Suchergebnisse hängen an einem
Fall — der erste Schritt ist also immer, einen Fall offen zu haben.

## Einen Fall anlegen

1. Gehen Sie zu **Fälle** und klicken Sie oben rechts auf **„Neuer Fall"**.
2. Füllen Sie aus:
   - **„Titel"** (Pflicht) — ein kurzer Name für die Ermittlung.
   - **„Priorität"** — *Normal*, *Hoch* oder *Dringend* (Vorgabe *Normal*).
3. Bestätigen. Der Fall erhält automatisch eine **Fallnummer**.

> Sie können einen Fall auch direkt im Suchformular anlegen — über die
> Schaltfläche **„Neu"** neben *„Fall zuordnen"*.

Eine **Beschreibung** gibt es im Anlegedialog nicht — sie lässt sich später
im Fall über **„Bearbeiten"** ergänzen.

## Die Fallliste

Die Tabelle **Fälle** zeigt **„Fallnummer"**, **„Titel"**, **„Status"**,
**„Priorität"** und **„Erstellt"**. Ein Klick auf eine Zeile öffnet den Fall.

Ein **Rechtsklick** auf eine Zeile bietet Schnellaktionen: *„Fall öffnen"*,
*„Fallnummer kopieren"*, *„ID kopieren"* und (nur für Admins) *„Löschen"*.

## Im Fall

Die Kopfzeile zeigt Fallnummer, Titel sowie Status- und Prioritätsetiketten,
dazu Schaltflächen:

- **„PDF-Bericht"** — ein geschriebener Bericht zum Fall (siehe
  [Berichte](08-reports.md)).
- **„Export"** — derselbe Fall als CSV, Maltego, MISP oder STIX
  ([Exportieren](14-exporting.md)).
- **„Bearbeiten"** — Titel, **Beschreibung**, Status (*Offen / In Bearbeitung
  / Geschlossen / Archiviert*), Priorität oder **„Zugewiesen an"** ändern.
- **„Löschen"** — nur für Admins.

Darunter liegen die Registerkarten des Falls:

1. **„Funde"** — die Ergebnisse als Arbeitsliste, nach Relevanz sortiert
   ([wie Funde bewertet werden](12-assessing-findings.md)). Hier beginnen Sie.
2. **„Netzwerkgraph"** — die visuelle Karte aller Funde
   ([wie man ihn liest](06-reading-the-graph.md)).
3. **„Karte"** — jeder Fund mit Koordinaten, geografisch dargestellt, mit
   einer Zeitleiste daneben. Sinnvoll erst, wenn der Fall verortete Funde
   enthält (Orte, Bewertungen, Bilder mit Geodaten).
4. **„Liste (N)"** — dieselben Entitäten als durchsuchbare, sortierbare
   Tabelle.
5. **„Neu seit letztem Lauf"** — was die jüngste Suche ergänzt hat
   ([Veränderungen verfolgen](13-tracking-changes.md)).
6. **„Neue Suche"** — eine Suche starten, deren Ergebnisse direkt in diesen
   Fall fallen ([wie Suchen funktionieren](03-searching.md)).

## Ergebnisse aufräumen

Während die Ergebnisse eintreffen, wollen Sie Signal von Rauschen trennen:

- **Als relevant markieren** — hebt eine zentrale Entität hervor (goldener
  Stern + Hof im Graphen), damit sie auffällt und im Bericht prominent
  erscheint.
- **„Als Fehltreffer entfernen"** — löscht eine Entität samt ihren
  Verbindungen aus dem Fall, wenn sie eindeutig Rauschen ist.

Beides erreichen Sie per Rechtsklick auf einen Knoten, über das
Knotendetail-Fenster oder in der Spalte *Aktionen* der Registerkarte
**Liste**.

## Suchprotokoll

Der Reiter **„Suchprotokoll"** listet jede Suche im Fall: wann, von wem, mit
welchem Suchbegriff und mit welchem **Zweck / welcher Rechtsgrundlage**.
Automatische Nachsuchen einer Überwachung erscheinen als *„Automatische
Nachsuche"*. Das Protokoll liegt im Datenspeicher Ihrer Behörde; der
Plattformbetreiber kann es nicht lesen.

## Fall-Vorlagen

Beim Anlegen eines Falls können Sie eine **Vorlage (Deliktsart)** wählen —
Ransomware, Phishing, Darknet-Handel, Sextortion usw. Sie ist ein
Ausgangspunkt, keine Vorschrift:

- die **Suche** im Fall wählt das passende Playbook (Module) vor,
- der **Bericht** startet mit einer zur Deliktsart passenden Gliederung,
- ein blaues Schild im Fallkopf nennt die Vorlage; beim Darüberfahren zeigt es
  die **typischen nächsten Werkzeuge**, ein Klick öffnet die Suche.

Die Vorlage lässt sich jederzeit über **Bearbeiten** ändern oder entfernen.

## Eingeschränkte Fälle (Need-to-know)

Standardmässig sieht jede Person Ihrer Behörde jeden Fall. Schalten Sie beim
Anlegen oder Bearbeiten **„Zugriff"** ein, um einen Fall **einzuschränken**:
dann sehen ihn nur die **Person, die ihn angelegt hat**, die **zugewiesene
Person**, die eingetragenen **Mitglieder** und die **Administration** Ihrer
Behörde. Für alle anderen existiert der Fall nicht — er fehlt in Listen,
Suchen, Alarmen und Überwachungen, und sein Link meldet „nicht gefunden".

- Nur wer den Fall angelegt hat, oder die Administration, kann den Zugriff
  ändern. Mitglieder arbeiten im Fall, können den Kreis aber nicht erweitern.
- Mitglieder sind Benutzernamen. Auch Kolleginnen und Kollegen, die sich noch
  nie angemeldet haben, können eingetragen werden.
- Jede Änderung des Zugriffs steht im **„Suchprotokoll"** des Falls.
- Die Administration ist bewusst eingeschlossen: jemand muss einen Fall neu
  zuweisen können, wenn die ermittelnde Person nicht mehr da ist.

## Beweise sichern

Ein Fund ist ein Link — wird die Seite gelöscht, bleibt nur die Behauptung.
**„Seite sichern"** (in der Knotenkarte eines Fundes mit Quellseite, oder im
Reiter **„Beweise"** für jede eingetippte Adresse) lädt die Seite in einem
echten Browser und legt im Datenspeicher Ihrer Behörde ab:

- ein **Bildschirmfoto der ganzen Seite** (PNG),
- ein **Archiv** der Seite mit Bildern und Formatierung (MHTML — öffnet in
  Chrome oder Edge),
- die **SHA-256-Prüfsumme** jeder Datei, die Endadresse nach Weiterleitungen,
  den HTTP-Status, den Zeitpunkt, wer gesichert hat und ob Tor benutzt wurde.

`.onion`-Seiten werden über Tor geladen und können über eine Minute dauern.
Interne Adressen werden abgewiesen. Mit der Prüfsumme kann jede Stelle später
nachweisen, dass eine heruntergeladene Datei genau die gesicherte ist — unter
Windows: `certutil -hashfile datei.mhtml SHA256`. Jede Sicherung steht auch im
**„Suchprotokoll"**. Der Plattformbetreiber kennt nur die Prüfsummen, nie die
Seite.

---

Weiter: **[Eine Suche durchführen →](03-searching.md)** · Zurück: **[Erste Schritte](01-getting-started.md)**
