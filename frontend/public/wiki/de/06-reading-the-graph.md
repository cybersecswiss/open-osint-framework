# Den Graphen lesen

Die Registerkarte **„Netzwerkgraph"** zeichnet alles in einem Fall als Netz:
**Knoten** sind Entitäten (Personen, Konten, Kanäle, Adressen, Nachrichten …),
**Kanten** sind die Beziehungen dazwischen. Die **Farbe** eines Knotens steht
für den Entitätstyp, die **Grösse** wächst mit seiner Vernetzung.

## Bedienelemente (linke Seitenleiste)

- **„Layout"** — wie die Knoten angeordnet werden: Breitensuchbaum (Vorgabe),
  *Force (fcose)*, *Konzentrisch*, *Kreis*, *Raster* oder *Force (cose)*.
- **„Zeichengrenze"** — grosse Fälle können Tausende Knoten haben; dies
  begrenzt, wie viele gleichzeitig gezeichnet werden (Vorgabe 100, bis 1000).
  Das Abzeichen zeigt *sichtbar / gesamt*.
- **„Alle Beschriftungen zeigen"** — jeden Knoten beschriften statt nur beim
  Überfahren.
- **„Nach Typ filtern"** — zugleich die **Legende**: ein farbiger Eintrag je
  Entitätstyp mit Anzahl. Ein Häkchen entfernen blendet den Typ aus.
- **„Einpassen"** rahmt alles ein · **„Wiederholen"** spielt die
  Layout-Animation erneut ab · **„Bildschirmfoto"** lädt ein PNG der
  aktuellen Ansicht herunter.
- Unten rechts die **Zoom**-Steuerung (Schaltflächen + Schieber, 10–400 %);
  das Mausrad zoomt ebenfalls.

## Mit Knoten arbeiten

- **Klick** auf einen Knoten → das **Detailfenster** öffnet sich rechts.
- **Doppelklick** auf einen Knoten → **„Suche von hier erweitern"**: Die
  Plattform startet eine *neue* Suche ausgehend von diesem Knoten (ein
  Doppelklick auf einen Telegram-Kanal startet z. B. eine Kanalsuche) und legt
  die Ergebnisse in denselben Fall.
- **Rechtsklick** auf einen Knoten → ein Menü: *„Details anzeigen"*, *„Suche
  von hier erweitern"*, *„Als relevant markieren"* / Markierung aufheben,
  *„Zur Überwachung hinzufügen…"*, *„Als Fehltreffer entfernen"* sowie
  Beschriftung bzw. ID kopieren.
- **Überfahren** hebt einen Knoten und seine Verbindungen hervor; das
  Überfahren einer hervorgehobenen Kante zeigt ihre **Beziehungsbezeichnung**
  (z. B. `MEMBER_OF`, `FORWARDED_FROM`). Kanten sind gerichtet (Pfeilspitzen).
- **Relevante** Knoten erhalten einen goldenen Rand und einen Hof.

Leerer Graph? *„Keine Daten — führen Sie eine Suche durch, um das Netz
aufzubauen."*

## Das Knoten-Detailfenster

Ein ausgewählter Knoten zeigt:

- Kopf-Etiketten: den **Entitätstyp**, die **Plattform** (falls vorhanden),
  einen **Confidence**-Prozentwert und ein goldenes **★ relevant**, falls
  markiert.
- Die **Beschriftung** des Knotens, eine anklickbare **URL**, falls vorhanden,
  danach eine Tabelle aller Datenfelder, die die Quelle zurückgegeben hat
  (URLs werden zu Links, Hashes erhalten eine Kopierschaltfläche, Listen
  werden als Aufzählung dargestellt).
- Aktionsschaltflächen: **„Überwachung aktivieren"**, **relevant**
  markieren/aufheben und **„Als Fehltreffer entfernen"**.

## Qualität am Graphen ablesen

Zwei visuelle Hinweise tragen die Einschätzung der Plattform:

- **Ein Doppelring** bedeutet, dass zwei oder mehr unabhängige Werkzeuge
  diesen Knoten gemeldet haben. Das ist das stärkste Signal, das das System
  erzeugt. Beachten Sie: Die **Grösse** eines Knotens folgt der Anzahl seiner
  Verbindungen, wodurch die lauteste Quelle optisch dominiert — der Ring ist
  das Gegengewicht und markiert den am besten *belegten* Knoten statt den
  geschäftigsten.
- **Der Bewertungs-Chip** (z. B. `B2`) auf der Knotenkarte ist die
  Admiralty-Bewertung: Quellenzuverlässigkeit als Buchstabe, Glaubwürdigkeit
  genau dieser Aussage als Ziffer.

Beides ist vollständig unter [Funde bewerten](12-assessing-findings.md)
erklärt — einmal lesenswert, denn die Bewertungen ändern, wie Sie priorisieren
sollten.

Die Knotenkarte hat ausserdem ein **Notizfeld**. Was Sie dort schreiben,
bleibt beim Fund, reist in Bericht und Export mit und liegt in der Datenbank
Ihrer eigenen Behörde. Nutzen Sie es für die Begründung, die eine Bewertung
nicht erfassen kann: warum Sie glauben, dass dieses Konto derselben Person
gehört, was Sie bereits geprüft haben, was noch zu verifizieren ist.

## Den Fall bearbeiten

Ein bewährter Rhythmus: Suche starten → **Funde** öffnen und von oben nach
unten arbeiten (die Liste ist nach Relevanz sortiert) → interessante Knoten
**anklicken**, Details und Belegstelle lesen → mit der **Erweiterten Suche**
tiefer pivotieren, damit Sie auswählen, was hinzukommt → was zählt **als
relevant markieren**, Fehltreffer **entfernen** und das Warum **notieren**.
Wiederholen, bis das Bild vollständig ist, dann einen
[Bericht](08-reports.md) oder einen [Export](14-exporting.md) erzeugen.

Bei einem Fall, zu dem Sie zurückkehren, beginnen Sie stattdessen mit
**[Neu seit letztem Lauf](13-tracking-changes.md)**.

## Knoten zusammenführen

Bezeichnen zwei Knoten dieselbe Person oder Sache — zwei Benutzernamen einer
Person, zwei Schreibweisen einer Firma —, öffnen Sie einen davon und wählen
**„Zusammenführen…"**. Wählen Sie die anderen; sie gehen im geöffneten Knoten
auf:

- ihre **Verbindungen** wandern über (eine Verbindung, die dann doppelt
  bestünde, wird zu einer, mit beiden Quellen dahinter),
- ihre **Quellen** zählen für den verbleibenden Knoten, was seine Bewertung
  anheben kann,
- Notizen und Quelladresse wandern mit, ihre Namen bleiben als **„Auch bekannt
  als"** sichtbar,
- **künftige Suchen**, die einen zusammengeführten Namen finden, ordnen ihn dem
  verbleibenden Knoten zu, statt ihn neu anzulegen,
- Überwachungen und Alarme wandern mit.

Das Zusammenführen lässt sich nicht rückgängig machen und steht im
**„Suchprotokoll"**. Wollen Sie nur eine Verbindung festhalten, ohne über die
Identität zu entscheiden, ziehen Sie stattdessen eine Verbindung.

## Gleicher Fund in anderen Fällen

Kommt ein Fund dieses Falls — eine E-Mail-Adresse, ein Benutzername, eine
Wallet — auch in einem **anderen Fall Ihrer Behörde** vor, meldet das eine
gelbe Leiste über den Reitern, und die Knotenkarte zeigt **„auch in
2026-…"**; ein Klick öffnet diesen Fall. Genannt werden nur Fälle, die Sie
öffnen dürfen: ein eingeschränkter Fall, zu dem Sie nicht gehören, erscheint
hier nie. Der Abgleich ignoriert Gross-/Kleinschreibung und läuft im
Datenspeicher Ihrer Behörde.

---

Weiter: **[Funde bewerten →](12-assessing-findings.md)** · Zurück: **[Telegram-Werkzeuge](05-telegram.md)**
