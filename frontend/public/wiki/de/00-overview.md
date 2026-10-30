# OSINT-Plattform — Benutzerhandbuch

Willkommen. Dieses Handbuch erklärt, wie Sie auf der OSINT-Plattform
Ermittlungen führen: anmelden, einen Fall anlegen, über Datenquellen suchen,
den Beziehungsgraphen lesen, Ziele über die Zeit überwachen und Berichte
erzeugen.

Es richtet sich an **Ermittlerinnen und Ermittler** (Endanwender). Einrichtung,
Server und Zugangsdaten sind getrennt im Betreiberhandbuch beschrieben
(`docs/operations.de.md`).

## Inhalt

1. **[Erste Schritte](01-getting-started.md)** — Anmeldung mit Ihrer
   dienstlichen E-Mail-Adresse und Orientierung in der Oberfläche.
2. **[Mit Fällen arbeiten](02-cases.md)** — jede Ermittlung liegt in einem
   Fall; anlegen und verwalten.
3. **[Eine Suche durchführen](03-searching.md)** — der Kernablauf:
   Abfragetyp wählen, Selektor eingeben, Module auswählen, Fortschritt lesen.
4. **[Module & Werkzeuge](04-modules-and-tools.md)** — die Erhebungsmodule
   und jedes Werkzeug darin.
5. **[Telegram-Werkzeuge (tief)](05-telegram.md)** — authentifizierte
   Telegram-Erhebung: Kanalscans, Nutzer-, Telefon- und Geo-Abfragen.
6. **[Den Graphen lesen](06-reading-the-graph.md)** — wie Sie die Entitäten
   und Beziehungen einer Suche erkunden.
7. **[Funde bewerten](12-assessing-findings.md)** — Bewertung,
   Kreuzbestätigung, Relevanz und Belegstellen: entscheiden, welche von
   mehreren hundert Ergebnissen tatsächlich zählen.
8. **[Veränderungen verfolgen](13-tracking-changes.md)** — was ein erneuter
   Lauf ergänzt hat, und was die Plattform bewusst **nicht** sagen kann.
9. **[Die KI-Funktion](11-ai-function.md)** — unterstütztes Verknüpfen, sofern
   lizenziert.
10. **[Überwachung & Alarme](07-monitoring-and-alerts.md)** — ein Ziel
    beobachten und benachrichtigt werden, wenn sich etwas ändert.
11. **[Berichte](08-reports.md)** — einen Fall zu einem weitergebbaren
    Bericht machen.
12. **[Fall exportieren](14-exporting.md)** — CSV, Maltego, MISP und STIX für
    die Weitergabe an ein anderes System oder eine andere Behörde.
13. **[Referenz & Glossar](09-reference.md)** — Abfragetypen, Entitätstypen,
    Kantenbeziehungen und Fehlerbehebung.
14. **[Support & Tickets](10-support.md)** — den Betreiber erreichen.

## In einer Minute

1. Plattform-URL öffnen und mit der **dienstlichen E-Mail-Adresse** anmelden.
2. Einen **Fall** für die Ermittlung anlegen.
3. Den Fall öffnen und eine **Suche** starten: *Abfragetyp* wählen
   (Benutzername, E-Mail, Domain, IP, Telefon, Telegram-Kanal,
   Krypto-Adresse …), den Selektor eingeben, die **Module** ankreuzen und
   starten.
4. Die Ergebnisse erscheinen als **Graph** aus Entitäten und Beziehungen im
   Fall. Ein Klick auf einen Knoten zeigt Details, ein Doppelklick pivotiert
   tiefer.
5. Optional **Überwachung** einrichten oder einen **Bericht** erzeugen.

> **Ihre Daten bleiben Ihre.** Ermittlungsdaten (Fälle, Entitäten,
> Ergebnisse) liegen im System Ihrer eigenen Organisation. Der
> Plattformbetreiber betreibt die Software, kann Ihre Falldaten aber nicht
> lesen.

---

Hier starten: **[Erste Schritte →](01-getting-started.md)**
