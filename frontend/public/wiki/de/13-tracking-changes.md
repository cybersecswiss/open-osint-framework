# Veränderungen in einem laufenden Fall verfolgen

In einem Fall, der über Wochen offen bleibt, lautet die Frage selten „was
haben wir" — sondern **„was ist seit dem letzten Mal neu"**. Zwei Funktionen
beantworten das: die Registerkarte *Neu seit letztem Lauf* für Suchen, die Sie
selbst gestartet haben, und die Überwachung für die, die von allein laufen.

## „Neu seit letztem Lauf"

Öffnen Sie einen Fall und wählen Sie die Registerkarte **Neu seit letztem
Lauf**. Sie zeigt, was die jüngste Suche ergänzt hat: neue Funde, neue
Beziehungen und aus welchem Lauf sie stammen.

Diese Ansicht gibt es, weil eine wiederholte Suche bewusst *idempotent* ist —
ein Fund, der bereits im Fall lag, behält seine Identität, statt ein zweites
Mal hinzugefügt zu werden. Das ist das richtige Verhalten, und genau deshalb
sieht ein erneuter Lauf so aus, als sei nichts passiert. Hier wird der
Unterschied sichtbar.

**Was als neu zählt.** Die Grenze ist der Startzeitpunkt der Suche; alles, was
danach in Ihrem Fall gespeichert wurde, ist ein Zugang. Ein Fund, der bereits
existierte und lediglich erneut bestätigt wurde, erscheint **nicht**. Das ist
wichtiger, als es klingt: Jeder erneute Lauf aktualisiert die Provenienz
bestehender Funde, und würde man das als Entdeckung zählen, sähe jeder Lauf
wie ein Durchbruch aus.

### Was sie Ihnen nicht sagt

**Verschwinden wird nicht erfasst, und die Ansicht sagt das auch.**

Wenn ein Leak-Site-Eintrag verschwindet oder ein Profil gelöscht wird,
erscheint das hier nicht. Der Grund ist ehrlich, nicht technisch: Ein
Werkzeug, das schlicht fehlgeschlagen ist, und eine echte Löschung sehen von
innerhalb der Plattform identisch aus. Das Zweite zu melden, wenn es in
Wahrheit das Erste war, wäre schlechter als zu schweigen — also schweigt die
Plattform, und zwar hörbar.

Ist das Verschwinden für Ihren Fall erheblich, gilt die bewährte Methode:
Sichern Sie den Beweis, wenn Sie ihn sehen (Bildschirmfoto, Export,
Belegstelle), statt zu erwarten, dass das Werkzeug sein Fehlen später bemerkt.

## Überwachung

Wo die Delta-Ansicht beantwortet, „was hat mein letzter Lauf ergänzt",
beantwortet die Überwachung: „sag mir Bescheid, wenn sich etwas ändert,
während ich nicht hinschaue".

Richten Sie eine Überwachung auf einen Fall ein, wiederholt die Plattform die
Suche nach Zeitplan und löst einen Alarm aus, wenn sich das Ergebnis ändert.
Einrichtung und Verwaltung sind unter
[Überwachung & Alarme](07-monitoring-and-alerts.md) beschrieben.

Beide ergänzen sich gut: Die Überwachung sagt Ihnen, *dass* sich etwas bewegt
hat, die Delta-Ansicht zeigt *was*.

## Ein praktischer Arbeitsablauf

Für einen Fall in aktiver Bearbeitung:

1. Die Suche erneut starten — oder die Überwachung das tun lassen.
2. **Neu seit letztem Lauf** öffnen; das ist der kürzeste Weg zum Neuen.
3. Die Zugänge von oben nach unten abarbeiten; sie sind nach demselben
   Relevanzwert sortiert wie überall sonst (siehe
   [Funde bewerten](12-assessing-findings.md)).
4. Markieren, was zählt, das Warum notieren, den Rest liegen lassen — er
   bleibt im Fall und kostet nichts.
5. Einen Bericht erzeugen, wenn Sie eine Momentaufnahme brauchen. Der Bericht
   beschreibt immer den Fall, wie er steht, nicht nur das Delta.

> **Einen alten Fall einmal neu zu scannen lohnt sich für sich genommen.**
> Funde, die vor der Einführung von Bewertung und Belegstellen erhoben wurden,
> bleiben unbewertet, bis ihre Quelle erneut gefragt wird. Ein einziger
> erneuter Lauf füllt das auf — ohne Dubletten, weil die Identität stabil ist.
