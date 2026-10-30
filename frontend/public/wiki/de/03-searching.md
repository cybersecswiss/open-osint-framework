# Eine Suche durchführen

Die Suche ist der Kernablauf: Sie geben der Plattform einen **Selektor**
(Benutzername, E-Mail, Domain, IP, Telefonnummer, Krypto-Adresse,
Telegram-Handle …), sie lässt die passenden **Module** laufen, und die
Ergebnisse bauen den Fallgraphen auf.

Suchen können Sie über die Seite **Suche** oder über die Registerkarte
**„Neue Suche"** innerhalb eines Falls. Im Fall aktualisieren die Ergebnisse
den Graphen an Ort und Stelle; von der eigenständigen Seite erhalten Sie eine
Fortschritts-URL, die Sie als Lesezeichen speichern können.

## Wo anfangen: die Seite „Lagebild"

Wenn Sie noch keinen Selektor haben, öffnen Sie **Lagebild** im Menü. Dort
sind Phänomenbereiche aus öffentlichen Lageberichten aufgeführt — Jahresbericht
von fedpol, *Sicherheit Schweiz* des NDB, Europol —, jede Karte mit Quelle und
Datum.

Ein Klick auf **„Übernehmen"** öffnet das Suchformular vorbefüllt mit dem
Begriff und einer sinnvollen Eingrenzung (z. B. *Rockerkriminalität* +
*Schweiz*). Es läuft nichts, bevor Sie **Suche starten** drücken — Begriff,
Eingrenzung und Module können Sie vorher ändern.

> **Was der Katalog ist und was nicht.** Er beschreibt *Phänomenbereiche*,
> keine Verdächtigen. Er bezeichnet keine Organisation als Bedrohung und
> begründet keinen Verdacht; jede Aussage gehört der zitierten Quelle, nicht
> diesem Werkzeug. Die Einträge sind Rechercheeinstiege.

Der Katalog ist eine Datei (`threat-catalog/catalog.json`), die Ihre
Administration jederzeit erweitern oder korrigieren kann — ohne
Softwareaktualisierung. Fragen Sie dort nach, wenn ein für Ihre Arbeit
relevanter Phänomenbereich fehlt.

## Schritt für Schritt

1. **„Suchbegriff / Indikator"** — geben Sie ein, was Sie untersuchen. Der
   Platzhalter zeigt die Idee: *„z. B. anonymous99, max@example.com,
   1.2.3.4, example.com, sha256:…"*.
2. **„Typ"** — wählen Sie, wie der Begriff zu verstehen ist (Benutzername,
   E-Mail, Domain, IP, URL, Hash, Telefon, Bitcoin-/Ethereum-Adresse, die
   Telegram-Typen, Discord-Einladung, **Bild-URL** oder Stichwort). Das ist
   die entscheidende Wahl — sie bestimmt, welche Module laufen können. Die
   vollständige Liste steht in der [Referenz](09-reference.md#query-types).
3. **„Fall zuordnen"** — den Fall wählen (oder über **„Neu"** einen anlegen).
   Innerhalb eines Falls ist das bereits gesetzt.
4. **„Module"** — die Erheber ankreuzen. **Es werden nur Module angezeigt,
   die Ihren gewählten Typ verstehen**, und sie werden bei einem Typwechsel
   automatisch ausgewählt. Zeigen Sie mit der Maus auf ein Modul, um zu
   sehen, welche seiner Werkzeuge laufen. Unterstützt nichts den Typ,
   erscheint *„Keine Module für Typ … verfügbar"*.
5. **„Suche starten"** klicken (die Schaltfläche wechselt zu *„Suche läuft…"*).

### Playbooks — vom Delikt aus statt von der Modulliste

Über den Modul-Ankreuzfeldern finden Sie **Playbooks**: Voreinstellungen für
gängige Deliktsfelder — Ransomware, Phishing, Darknet-Handel, Betrug/Fake-Shop,
Kryptobetrug, Sextortion, Infrastruktur. Ein Playbook kreuzt die Module an, die
sich für diese Art Fall lohnen.

Es ist reine Konfiguration: Ein Playbook tut nichts, was Sie nicht von Hand
tun könnten — es erspart Ihnen nur die Entscheidung, welche von einem Dutzend
Modulen ihre Laufzeit wert sind. Zwei Details machen sie verlässlich:

* Sie sehen nur Playbooks, für die Ihre Behörde lizenziert ist — eine
  Voreinstellung kann nie ein Modul anbieten, das anschliessend abgelehnt
  würde.
* Jeder Eintrag sagt Ihnen, ob er zum aktuell getippten **Typ** passt; eine
  für Domains gebaute Voreinstellung wird für einen Benutzernamen also nicht
  angeboten.

Die Kreuze können Sie danach anpassen. Das Playbook ist ein Startpunkt, keine
Einstellung.

## Erweiterte Suche: erst sehen, dann übernehmen

Die gewöhnliche Suche fügt dem Fall alles hinzu, was sie findet. Das ist
richtig, wenn Sie eine Spur eröffnen — und falsch, wenn Sie einer folgen: Ein
einziger breiter Pivot kann einen Fall in Rauschen begraben.

Die **Erweiterte Suche** (die Schublade *Erweiterte Suche*, auch von jedem
Knoten im Graphen erreichbar) führt dieselbe Erhebung durch, **speichert aber
nichts**. Sie erhalten die Kandidaten als Vorschau, wobei die bereits im Fall
vorhandenen gekennzeichnet sind, und kreuzen an, was übernommen wird. Nur das
wird geschrieben.

Das ist Absicht, und nicht nur der Ordnung wegen: **Die Entscheidung, einen
Fund mit einem anderen zu verknüpfen, trifft ein Mensch.** Die Plattform zeigt
Ihnen, dass ein Benutzername auf elf Seiten auftaucht; sie entscheidet nicht an
Ihrer Stelle, dass es dieselbe Person ist. In einer Akte ist genau diese
Unterscheidung die, die halten muss.

Nutzen Sie sie immer dann, wenn Sie von einem Fund aus pivotieren statt von
einem frischen Selektor — nach der ersten Suche also meistens.

> **Optionale Felder.** *„E-Mail (optional)"*, *„Telefon (optional)"*,
> *„Priorität (optional)"* und *„Notiz (optional)"* sind Bequemlichkeiten:
> Die Notiz wird der Fallbeschreibung mit Zeitstempel und Ihrem Namen
> angehängt. Die Suche selbst nutzt nur das Feld *„Suchbegriff"*.

## Eine Stichwortsuche eingrenzen („Eingrenzen")

Ein Begriff wie **Crimson Wolves** liefert Treffer aus aller Welt. Ist der
Suchtyp **Stichwort**, erscheint ein Feld **„Eingrenzen"**, in dem Sie
Eingrenzungsbegriffe wählen — oder frei eintippen — können:

* **Region** — Schweiz, Deutschschweiz, Romandie, Ticino
* **Kanton** — alle 26, unter ihren amtlichen Namen (Zürich, Genève, Ticino …)
* **International** — Europa, International, Nachbarländer
* **Deliktsfeld** — Drogenhandel, Waffenhandel, Geldwäscherei …
* **alles, was Sie selbst eintippen** — eine Stadt, ein Quartier, ein Milieu

Jeder Eingrenzungsbegriff startet **einen zusätzlichen Suchlauf** mit
angehängtem Begriff. „Crimson Wolves" plus „Schweiz" und „Zürich" ergibt drei
Suchen: den blossen Begriff, `Crimson Wolves Schweiz` und `Crimson Wolves Zürich`.
Das Feld zeigt *vor* dem Start an, wie viele Läufe Ihre Auswahl kostet.

Alle Ergebnisse landen im **selben Fall**. Im Graphen sehen Sie, wie sich der
Grundbegriff in die eingegrenzten verzweigt — Sie erkennen also, **welche
Eingrenzung welchen Treffer erzeugt hat**. Dienste, die mehrere Läufe finden,
erscheinen einmal, nicht mehrfach.

> **Warum die Grenze von fünf?** Jeder Lauf fragt jedes Werkzeug jedes
> gewählten Moduls ab. Fünf Eingrenzungsbegriffe über vier Werkzeuge sind
> bereits zwei Dutzend Anfragen, und mehrere Quellen drosseln uns bei diesem
> Volumen. Wenige, gut gewählte Eingrenzungen liefern bessere Ergebnisse als
> viele breite.

> Eingrenzen gilt nur für **Stichwort**-Suchen. „Zürich" an eine
> E-Mail-Adresse oder eine Bitcoin-Adresse anzuhängen ergäbe einen Selektor,
> der auf nichts passt — für diese Typen ist das Feld daher ausgeblendet.

## Zweck / Rechtsgrundlage

Das Feld **„Zweck / Rechtsgrundlage"** hält fest, warum gesucht wird —
Aktenzeichen, Verfügung, Auftrag. Es wird **nur im Suchprotokoll Ihrer
Behörde** gespeichert (Reiter **„Suchprotokoll"** im Fall), nie beim
Plattformbetreiber; dieser erfährt nur, *dass* ein Zweck angegeben wurde.

- Innerhalb eines Falls wird der zuletzt verwendete Zweck wieder vorgeschlagen.
- Hat Ihre Administration *„Zweck bei jeder Suche verlangen"* eingeschaltet
  (Admin → Einstellungen), wird eine Suche ohne Zweck abgewiesen. Ist das
  Suchprotokoll Ihrer Behörde in diesem Moment nicht erreichbar, wird die
  Suche **nicht gestartet** — was nicht protokolliert werden kann, läuft nicht.
- Dasselbe gilt beim Anlegen einer **Überwachung**; deren automatische
  Nachsuchen verweisen auf den bei der Anlage angegebenen Zweck.

## Den Fortschritt verfolgen

Die Suche fächert **parallel** zu allen passenden Werkzeugen auf. Eine
Live-Tabelle **„Werkzeugstatus"** aktualisiert sich alle 3 Sekunden mit einer
Zeile pro Werkzeug:

**Modul · Werkzeug · Status · Funde · Kanten · Dauer · Fehler**

Sie endet mit **„Abgeschlossen"**, **„Abgeschlossen (teilweise)"** (ein
Werkzeug lief auf einen Fehler, z. B. einen fehlenden API-Schlüssel),
**„Suche fehlgeschlagen"** oder **„Abgebrochen"** (Sie haben sie gestoppt —
siehe unten). Auf der eigenständigen Fortschrittsseite sehen Sie
zusätzlich **„Gefundene Entitäten"** und **„Verbindungen"** sowie eine
Schaltfläche **„Fall öffnen"**.

### Eine Suche abbrechen

Dauert eine Suche zu lange, oder haben Sie den falschen Selektor getippt,
stoppen Sie sie auf der Fortschrittsseite mit **„Suche abbrechen"**.

> **Was bereits gefunden wurde, bleibt.** Funde werden fortlaufend in den
> Fall geschrieben — der Abbruch stoppt nur die Werkzeuge, die noch laufen.
> Der Fortschrittsbalken bleibt deshalb dort stehen, wo die Suche wirklich
> war, und zeigt bewusst **nicht** 100 %: „abgebrochen" ist etwas anderes als
> „fertig", und im Fallbericht muss dieser Unterschied lesbar bleiben.
>
> **Ein Werkzeug kann noch kurz nachlaufen.** Der Abbruch beendet das Warten
> auf die Quelle; das angefragte Modul bemerkt es erst beim nächsten Schritt.
> Das ist unkritisch — Ergebnisse, die danach noch eintreffen, gehören zu
> einer beendeten Suche und werden nicht mehr übernommen.

> **Der Fortschrittsbalken bildet echte Arbeit ab** — er füllt sich, wenn ein
> Werkzeug fertig wird (z. B. *7 von 11 Werkzeugen fertig*), nicht nach einer
> festen Schätzung.
>
> **Ergebnisse werden gespeichert, sobald sie eintreffen.** Funde werden
> **fortlaufend, modulweise** in den Fall geschrieben — der Graph füllt sich
> während der Suche, Sie müssen nicht auf das langsamste Werkzeug warten.
>
> **Sie können weggehen.** Die Suche läuft auf dem Server. Den Tab zu
> wechseln, wegzunavigieren oder **den Browser neu zu laden** stoppt sie
> nicht und verliert den Fortschritt nicht — öffnen Sie den Fall (oder die
> Fortschritts-URL) erneut, und es läuft weiter.

> **Ein Werkzeug mit dem Hinweis „Schlüssel nicht gesetzt" ist kein
> Fehlschlag** — dieser einen Quelle fehlt ein API-Schlüssel, den Ihr
> Betreiber nicht hinterlegt hat. Alle anderen Werkzeuge sind trotzdem
> gelaufen. Ebenso ist **null Ergebnisse eine gültige Antwort** (z. B. eine
> E-Mail-Adresse, die in keinem Leak vorkommt).

## Was Sie erhalten

Jeder Fund wird zu einer **Entität** (einem Knoten) im Fall, Beziehungen
zwischen ihnen werden zu **Kanten**. Erfolgreiche Module speichern ihre
Ergebnisse auch dann, wenn ein anderes Modul auf einen Fehler lief. Wechseln
Sie zur Registerkarte **„Netzwerkgraph"**, um das Ergebnis zu erkunden.

Wie Sie aus mehreren hundert Funden die zwanzig herausarbeiten, die zählen,
steht unter [Funde bewerten](12-assessing-findings.md).

## News & RSS

**News & RSS** im Menü ist die gewöhnliche Suche mit vorausgewähltem
News-Modul. Sie führt eine Volltextsuche über die von Ihrem Betreiber
gepflegten Feeds durch — Bundesstellen, Polizei, Medien und Cyber-Quellen —
und liefert jeden Treffer als Knoten mit **Datum, Quelle und Quellenart**.

Die Quellenart ist beim Lesen des Graphen erheblich: Eine Behördenmeldung und
ein Zeitungsartikel sind beide legitime Spuren, tragen aber nicht dasselbe
Beweisgewicht. Amtliche Quellen erhalten zudem eine höhere Confidence.

Eingrenzen funktioniert auch hier, *Rockerkriminalität* + *Schweiz* durchsucht
die Feeds also nach beiden Begriffen zusammen. Und weil das News-Modul auf
schlichte Stichwörter reagiert, durchsucht ein aus dem **Lagebild**
übernommenes Thema die Nachrichtenquellen ohne zusätzlichen Schritt mit.

> **Was sie nicht tut.** Sie durchsucht die Einträge, die ein Feed
> veröffentlicht — Überschrift und Anriss —, nicht den Volltext verlinkter
> PDFs. Feeds reichen zudem nur so weit zurück, wie die Quelle sie
> veröffentlicht (typischerweise wenige Jahre). Ein fehlender Treffer heisst
> „nicht in diesen Feeds", nie „ist nicht geschehen".

Fehlt eine Quelle? Ihr Betreiber ergänzt sie in der Global-Admin-Konsole unter
**Einstellungen → RSS-Feeds**; sie gilt ab der nächsten Suche.

---

Weiter: **[Module & Werkzeuge →](04-modules-and-tools.md)** · Zurück: **[Mit Fällen arbeiten](02-cases.md)**
