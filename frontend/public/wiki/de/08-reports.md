# Berichte

Sie können jeden Fall in einen **PDF-Bericht** überführen — nützlich für die
Akte, für die Akteneinsicht oder zur Unterrichtung von Kolleginnen und
Kollegen.

## Einen Bericht erzeugen

1. Den Fall öffnen und in der Kopfzeile auf **„PDF-Bericht"** klicken (das
   öffnet die Seite **„PDF-Bericht erzeugen"**).
2. Unter **„Enthaltene Abschnitte"** die gewünschten Teile ankreuzen.
   Verfügbare Abschnitte, in der Reihenfolge ihres Erscheinens im Dokument:
   - **„Deckblatt"** — Logo, Fallnummer, Titel, Status
   - **Zusammenfassung** — was der Fall enthält, nach Typ aufgeschlüsselt
   - **Kernfunde** — die zwanzig höchstbewerteten Funde *mit der Begründung,
     warum jeder dort steht*: welche Werkzeuge ihn bestätigt haben und wie die
     Quelle eingestuft ist. Das ist der Abschnitt für jemanden, der nur einen
     einzigen liest.
   - **Entitätentabelle** — alle Funde, nach Relevanz statt alphabetisch
     sortiert
   - **Beziehungen** — wer mit wem verbunden ist, nach Typ gruppiert, **mit
     dem Werkzeug, das die jeweilige Verbindung behauptet hat**
   - **Graphbild** — ein Bild des Netzes, in dem Doppelringe die Funde
     markieren, die mehr als ein Werkzeug gemeldet hat
   - **Suchen** — welche Suchen diesen Fall erzeugt haben
   - **Alarme**
   - **Zeitleiste**
   - **Belegstellen** — der Zitatanhang: Quell-URL, Werkzeug sowie wann die
     Quelle es gesagt hat gegenüber dem Zeitpunkt der Speicherung

   Alle sind standardmässig ausgewählt; entfernen Sie, was Sie nicht brauchen.

> **Der Bericht schreibt hin, was er weggelassen hat.** Ist irgendetwas im
> Fall als relevant markiert, enthält der Bericht genau diese Funde;
> andernfalls enthält er alles, was nicht als Fehltreffer markiert ist. In
> beiden Fällen nennt er die angewandte Regel und wie viel sie unterdrückt hat
> — ein gefilterter Bericht, der nicht sagt, dass er gefiltert ist, wäre
> schlechter als ein ungefilterter. Platzhalter zählen nie als Funde (siehe
> [Funde bewerten](12-assessing-findings.md)).

3. Der Bericht wird in **Ihrer aktuellen Oberflächensprache** erzeugt (*„Der
   Bericht wird in {Sprache} erstellt…"*) — wechseln Sie zuvor die
   Sprachauswahl in der Kopfzeile, wenn Sie eine andere möchten.
4. Auf **„PDF erzeugen"** klicken. Die Datei wird als `{Fallnummer}.pdf`
   heruntergeladen, und Sie sehen **„Bericht heruntergeladen"**.

Schlägt es fehl, erscheint *„Berichtserzeugung fehlgeschlagen"* — versuchen
Sie es erneut oder wählen Sie weniger Abschnitte; hält es an, melden Sie es
Ihrem Betreiber.

## Hinweise

- **Markieren Sie zentrale Entitäten vorher als relevant** — markierte
  Entitäten treten im Bericht hervor, und sie steuern zugleich, was überhaupt
  aufgenommen wird.
- Das **Deckblatt** verwendet **Logo** und Anzeigenamen Ihrer Organisation,
  die eine Administration unter **Administration → Einstellungen** hinterlegt.
- Erzeugen Sie einen frischen Bericht, wenn sich der Fall weiterentwickelt
  hat; das PDF ist eine Momentaufnahme, kein lebendes Dokument.
- Soll ein *System* statt eines Menschen die Ergebnisse verarbeiten, nehmen
  Sie stattdessen den [Export](14-exporting.md).

## Berichtsoptionen

- **Nur als relevant markierte Funde (Auszug)** — Tabellen, Graph und
  gesicherte Seiten zeigen nur die mit ★ markierten Funde und die Verbindungen
  zwischen ihnen. Jede Seite trägt den Vermerk *„Auszug"*. Ohne Haken enthält
  der Bericht alle Funde ausser den als falsch markierten.
- **PDF oder Word** — Word dient der Weiterbearbeitung: gleicher Inhalt und
  gleiche Bilder, einfacheres Layout.
- Zwei weitere Abschnitte: **„Suchprotokoll"** (wer wann was mit welchem Zweck
  gesucht hat) und **„Gesicherte Seiten"** (Bildschirmfotos mit SHA-256, damit
  eine Leserin eine heruntergeladene Datei prüfen kann).
- Ein Fall mit **Vorlage** startet mit der Gliederung seiner Deliktsart.

---

Weiter: **[Fall exportieren →](14-exporting.md)** · Zurück: **[Überwachung & Alarme](07-monitoring-and-alerts.md)**
