# Funde bewerten

Eine Suche über ein Dutzend Module liefert routinemässig mehrere hundert
Knoten. Das Sammeln war nie das Schwierige — zu entscheiden, welche zwanzig
zählen, schon. Diese Seite erklärt die drei Mechanismen, die Ihnen die
Plattform dafür gibt, und ebenso wichtig: was jeder von ihnen **nicht**
behauptet.

## Die Bewertung (Admiralty)

Jeder Fund trägt eine zweistellige Bewertung wie **B2**. Es ist die
NATO-Admiralty-Skala, und sie beantwortet zwei getrennte Fragen, die eine
einzelne „Confidence"-Zahl früher vermischt hat.

**Der Buchstabe — wie zuverlässig ist die Quelle?** Pro Werkzeug deklariert,
denn nur wer das Werkzeug gebaut hat, weiss, welche Art von Aussage es macht.
Ein Treffer in einem Zertifikatsregister ist eine andere Art von Tatsache als
ein Treffer auf einer abgegriffenen Profilseite — auch wenn beide
„funktioniert" haben.

| | Bedeutung |
|---|---|
| **A** | Vollständig zuverlässig — autoritatives Register oder Primärquelle |
| **B** | In der Regel zuverlässig |
| **C** | Einigermassen zuverlässig |
| **D** | Meist nicht zuverlässig |
| **E** | Unzuverlässig |
| **F** | **Nicht beurteilbar** — das Werkzeug deklariert nichts |

**F ist eine ehrliche Lücke, keine schlechte Note.** Es bedeutet, dass diese
Quelle niemand eingestuft hat. Lesen Sie es nicht als „schwacher Beleg",
sondern als „nicht eingestuft".

**Die Ziffer — wie glaubwürdig ist genau diese Aussage?** Von der Plattform
pro Fund abgeleitet, denn nur sie sieht, ob andere Werkzeuge zugestimmt haben.

| | Bedeutung |
|---|---|
| **1** | Durch andere Quellen bestätigt — **zwei oder mehr unabhängige Werkzeuge haben dasselbe gemeldet** |
| **2** | Wahrscheinlich wahr |
| **3** | Möglicherweise wahr |
| **4** | Zweifelhaft |
| **6** | Nicht beurteilbar |

**Die 5 („unwahrscheinlich") wird nie vergeben.** Nichts in der Erhebungskette
kann rechtfertigen, aktiv gegen einen Fund zu argumentieren — also tut die
Plattform auch nicht so, als könnte sie das.

Eine Feinheit, die man kennen sollte: Melden mehrere Werkzeuge denselben
Knoten, ist der angezeigte Buchstabe die **beste** Zuverlässigkeit unter
ihnen. Liefern ein Register und ein Scraper denselben Wert, ist das Wort des
Registers massgeblich — eine schwache Zweitquelle kann die Glaubwürdigkeit
heben, aber nie die Zuverlässigkeit senken.

## Kreuzbestätigung

Unter der Bewertung sehen Sie die Werkzeuge, die denselben Fund unabhängig
gemeldet haben, z. B. **✓ 3**. Zeigen Sie mit der Maus darauf, um zu sehen,
welche.

Das ist das stärkste Signal, das das System erzeugt, und der Grund, warum die
Ziffer überhaupt **1** erreichen kann. Zwei Eigenschaften machen es
belastbar:

* Sie ist auf die **kanonische Identität** des Fundes bezogen, nicht auf die
  genaue Schreibweise — zwei Schreibweisen derselben Adresse zählen weiterhin
  als Übereinstimmung.
* Sie **sammelt sich über Suchen hinweg an**. Bestätigt ein Werkzeug einen
  Knoten Monate später, wird es der Liste hinzugefügt statt sie zu ersetzen.
  Genau diese Historie ist der erhaltenswerte Teil.

Im Graphen wird ein Knoten, den zwei oder mehr unabhängige Werkzeuge gemeldet
haben, mit einem **Doppelring** gezeichnet. Die Knotengrösse folgt der Anzahl
der Verbindungen, wodurch die lauteste Quelle optisch dominiert; der Ring ist
das Gegengewicht und markiert den am besten *belegten* Knoten statt den am
stärksten vernetzten.

## Relevanz-Rangfolge

Die Fundliste ist nach einem Relevanzwert sortiert, der aus vier Signalen
entsteht:

| Signal | Gewicht | Warum |
|---|---|---|
| Kreuzbestätigung | 40 % | Unabhängige Übereinstimmung ist am schwersten vorzutäuschen |
| Quellenzuverlässigkeit | 25 % | Der Admiralty-Buchstabe |
| Lage im Graphen | 20 % | Wie stark der Knoten vernetzt ist |
| Abstand zu Ihrem Selektor | 15 % | Schritte von dem entfernt, wonach Sie gesucht haben |

Der Wert wird **bei jedem Aufruf neu berechnet und nie gespeichert**.
Markieren Sie einen Fehltreffer oder lassen Sie ein weiteres Werkzeug laufen,
ändert sich die Reihenfolge sofort. Eine gespeicherte Spalte wäre ab dem
nächsten Klick veraltet, und Sie hätten keine Möglichkeit zu erkennen, welche
Zeilen noch aktuell sind.

Der Bericht verwendet denselben Wert auf dieselbe Weise. Die Reihenfolge auf
dem Bildschirm ist also die Reihenfolge, in der das PDF argumentiert. Es gibt
bewusst nur **eine** Rangfolge im System.

## Belegstellen

Wo ein Werkzeug eine Quelle gemeldet hat, trägt der Fund eine
**Belegstelle** — die Seite, aus der die Aussage stammt — sowie den Zeitpunkt,
zu dem die Quelle es gesagt hat (`beobachtet`), getrennt vom Zeitpunkt der
Speicherung in Ihrem Fall (`gefunden`). Bei schnelllebigen Quellen wie
Leak-Seiten, Pastes und Telegram ist der Beobachtungszeitpunkt der
beweiserhebliche.

> **Ältere Funde haben womöglich keine Belegstelle.** Eine Spalte kann nur
> füllen, wessen Werkzeug den Wert zurückgibt. Zeilen, die vor der Einführung
> der Provenienz erhoben wurden, bleiben leer, bis diese Quelle erneut
> abgefragt wird. Das ist eine Lücke im Nachweis, kein Fehler im Fund — und
> ein erneuter Lauf füllt sie auf, ohne Dubletten zu erzeugen.

## Platzhalter sind keine Funde

Manche Knoten existieren nur, um den Graphen zusammenzuhalten: Es wurde eine
Beziehung gemeldet, deren anderes Ende selbst nie bestätigt wurde. Diese sind
als Platzhalter gekennzeichnet, werden getrennt gezählt und erscheinen nie in
Berichten oder Exporten. Niemand hat sie behauptet, also belegen sie nichts.

Die einzige Ausnahme ist der Knoten des von Ihnen gesuchten Begriffs. Er ist
technisch virtuell, aber er ist der untersuchte Selektor und hält den halben
Graphen zusammen — er wird daher durchgehend als echt behandelt.

## Was Sie damit tun

Eine bewährte Reihenfolge:

1. Nach Relevanz sortieren (Vorgabe) und den Anfang der Liste zuerst lesen.
2. Funden mit **Ziffer 1** den Vorzug geben — hinter denen steht mehr als ein
   Werkzeug.
3. Die Belegstelle öffnen, bevor Sie sich auf etwas stützen. Die Bewertung
   sagt Ihnen, wie viel Gewicht eine Quelle verdient; sie sagt nie, dass der
   Fund wahr ist.
4. Was zählt, als relevant markieren (Stern) und Fehltreffer als solche
   kennzeichnen. Beides fliesst unmittelbar in die Rangfolge und in den
   Inhalt des Berichts zurück.
5. Das *Warum* ins Notizfeld am Knoten schreiben. Die Bewertung ist die
   Einschätzung der Plattform; die Notiz ist Ihre — und sie ist die, die in
   sechs Monaten noch verständlich ist.

Siehe auch: [Den Graphen lesen](06-reading-the-graph.md) ·
[Berichte](08-reports.md) · [Exportieren](14-exporting.md)
