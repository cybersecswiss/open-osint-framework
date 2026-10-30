# Firmen & Personen

Jedes andere Modul beginnt mit einem technischen Selektor — einem
Benutzernamen, einer Domain, einem Hash, einer Wallet. Dieses beginnt mit
einem **Namen**, und das ist der Einstieg, den ein Fall zu Beschaffung,
Sanktionsumgehung oder Scheinfirmen tatsächlich hat.

Wählen Sie den Abfragetyp **Firmenname** oder **Personenname**, geben Sie den
Namen ein und kreuzen Sie das Modul *Firmen & Personen* an. Alle fünf
Werkzeuge sind keylos.

## Was die einzelnen Werkzeuge beantworten

| Werkzeug | Die Frage, die es beantwortet | Bewertung |
|---|---|---|
| **CH-Handelsregister (SHAB)** | Existiert diese Firma in der Schweiz, wer zeichnet für sie, von welcher Adresse aus, und ist sie noch eingetragen? | A |
| **Konzernstruktur (GLEIF)** | Wem gehört sie, was besitzt sie, und unter welchen anderen Namen ist sie eingetragen? | A |
| **Sanktionsabgleich** | Steht dieser Name auf den EU- oder US-Sanktionslisten, unter welchem Programm? | A |
| **Wikidata-Verflechtung** | Wer leitet sie, wer hält Anteile, was gehört sonst zum selben Konzern? | C |
| **CH-Verzeichnis** | Wo geht physisch jemand ans Telefon? | B |

## Ein durchgespieltes Beispiel

Angenommen, Sie suchen nach der (fiktiven) Firma **Muster Trading SA** als
*Firmenname*. Eine solche Suche liefert typischerweise:

* die **Genfer Zweigniederlassung** aus dem Handelsregister — UID
  (`CHE-…`), Adresse, das zuständige kantonale Handelsregisteramt und, falls
  zutreffend, das Datum der **Löschung** samt Begründung;
* die **namentlich genannten Zeichnungsberechtigten**, etwa einen Direktor
  mit Einzelunterschrift, mit angegebener Staatsangehörigkeit und Wohnort —
  samt dem genauen Satz, den das Register gedruckt hat;
* den **Konzern**: die ausländische Muttergesellschaft mit ihrer LEI, ihre
  Namen in anderen Schriften und lateinischen Varianten, dazu die Töchter;
* die **Leitung** und Beteiligungen aus Wikidata.

Das sind vier verschiedene Arten von Nachweis über eine Organisation,
zusammengeführt in einem Graphen — und jeder trägt die Belegstelle mit, aus
der er stammt.

## Die Ergebnisse sorgfältig lesen

**Die Firma ist ein Nachweis. Die Personen sind aus Fliesstext geparst.**
Handelsregister-Publikationen nennen Organe in einem formelhaften Satz
(„Signature individuelle a été conférée à …", „…, von Zug, in Bern, Mitglied
des Verwaltungsrates"), nicht in einem strukturierten Feld. Das Werkzeug
extrahiert sie zurückhaltend und hängt jeder Person den **genauen Satz** an,
unter `register_statement`. Lesen Sie diesen Satz, bevor Sie sich auf den
Namen stützen. Deshalb kommen Personen auch mit einer niedrigeren Confidence
zurück als die Firma, zu der sie gehören.

**Ein „kein Sanktionstreffer" ist keine Unbedenklichkeitsbescheinigung.** Der
Abgleich ist bewusst exakt: Jedes Wort Ihrer Anfrage muss im gelisteten Namen
vorkommen. Das verhindert, die falsche Person zu belasten — und es bedeutet,
dass eine **abweichende Transliteration** nicht gefunden wird. Иванов und
Ivanov werden von der Maschine nicht einander zugeordnet; dieser Schluss ist
Ihrer, und Sie müssen ihn dokumentieren. Das Werkzeug nennt immer, wie viele
Namen es geprüft hat.

**Wikidata ist eine Spur, kein Nachweis.** Es wird von einer Gemeinschaft
gepflegt. Nutzen Sie es, um zu finden, *wo Sie hinschauen sollten* — eine
Tochtergesellschaft, ein Verwaltungsratspräsidium, eine Eigentümerin — und
bestätigen Sie den Fund dann in einem Register.

**Ein fehlender Verzeichniseintrag beweist nichts.** Eine nicht publizierte
Nummer fehlt bei tel.search.ch genau so wie eine nicht existierende.

## Wo das in einen Fall passt

Die natürliche Reihenfolge:

1. **Zuerst das Register** — es liefert die juristische Person, die Adresse
   und die Menschen, alles zitierfähig.
2. **Dann die Konzernstruktur** — die Mutter und die Schwestergesellschaften
   sind meist der Ort, an dem die eigentliche Gegenpartei sitzt.
3. **Sanktionsabgleich** über jeden Namen, den die ersten beiden Schritte
   ergeben haben — nicht nur über den, mit dem Sie begonnen haben.
4. **Erst dann technisch pivotieren**: Adresse und Personen speisen
   [gewöhnliche Suchen](03-searching.md) — die Firmendomain in `infra` und
   `theharvester`, den Namen eines Organs in die Alias-Werkzeuge, die
   Telefonnummer in die Messenger-Werkzeuge.

Das Playbook **Sanktionsumgehung / Beschaffung** stellt das mit einem Klick
ein.

## Ein Wort zur Sorgfalt

Ab hier arbeiten Sie mit **Personendaten realer Menschen**. Dass jemand als
Organ in einem Handelsregister steht, ist eine öffentliche Tatsache. Dass
dieselbe Person an einer Straftat beteiligt ist, ist eine Behauptung — Ihre,
und eine, die Sie belegen können müssen.

Die Plattform hält das bewusst auseinander: Werkzeuge sammeln, ein Mensch
verknüpft, und das Notizfeld am Knoten ist der Ort für Ihre Begründung. Nutzen
Sie es. In sechs Monaten wird es der einzige Nachweis dafür sein, *warum* Sie
zwei Funde verbunden haben — und genau das muss eine Akte zeigen können.

Siehe auch: [Funde bewerten](12-assessing-findings.md) ·
[Eine Suche durchführen](03-searching.md) · [Fall exportieren](14-exporting.md)
