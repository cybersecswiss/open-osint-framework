# Einen Fall exportieren

Neben der Berichtsschaltfläche bietet **Export** vier maschinenlesbare
Formate. Nehmen Sie den Bericht, wenn ein Mensch ihn lesen wird; nehmen Sie
einen Export, wenn ein *System* oder die Analystin einer anderen Behörde ihn
verarbeitet.

| Format | Wofür |
|---|---|
| **CSV** | Tabellenkalkulation, eigene Fallverwaltung, schnelles Filtern |
| **Maltego-CSV** | Import des Falls als Graph in Maltego |
| **MISP-Event** | Übergabe von Indikatoren an ein CERT / eine Threat-Intel-Plattform |
| **STIX 2.1** | Der internationale Standard für den Austausch von Cyber-Bedrohungsinformationen |

## Was mit einem Fund mitreist

Alle vier Formate tragen die Provenienz mit, denn ein Fund ohne Herkunft ist
für die empfangende Seite kein verwertbarer Beleg:

* das **Werkzeug**, das ihn gemeldet hat,
* jedes Werkzeug, das ihn **unabhängig bestätigt** hat,
* die **Admiralty-Bewertung**,
* die **Quell-URL**, sofern das Werkzeug eine geliefert hat.

## Zwei Regeln, die für jeden Export gelten

**Platzhalter verlassen das Haus nie.** Knoten, die nur existieren, um den
Graphen zusammenzuhalten, werden ausgeschlossen. Niemand hat sie behauptet,
und die empfangende Behörde hätte keine Möglichkeit, sie von bestätigten
Funden zu unterscheiden.

**Jeder Export wird protokolliert.** Die Audit-Kette hält fest, wer welchen
Fall wann in welchem Format exportiert hat, samt SHA-256-Prüfsumme der genauen
Nutzlast. Funde an eine andere Behörde zu übergeben ist genau die Art von
Handlung, die eine Akte später belegen können muss — einschliesslich des
Nachweises, dass das Gesendete dem Empfangenen entspricht.

## Formatspezifisches, das man wissen sollte

**MISP: Indikatoren sind nicht scharf geschaltet.** Attribute gehen mit
`to_ids=false` hinaus, solange Sie den Fund nicht als relevant markiert haben.
`to_ids=true` weist das empfangende System an, auf einen Indikator zu
*blockieren oder zu alarmieren* — ungeprüftes OSINT darf im Netz eines
Partners nicht feuerbereit ankommen. Einen Fund als relevant zu markieren ist
Ihre Aussage, dass Sie ihn geprüft haben; das setzt den Schalter um.

**STIX: Funde ausserhalb des Standardvokabulars werden deklariert.** OSINT
erzeugt Objekttypen, für die STIX keine Entsprechung hat. Statt sie still
wegzulassen oder falsch zu etikettieren, reisen sie als `x-osint-entity`, und
das Bundle trägt ein `note`-Objekt mit der Angabe, wie viele das betrifft. Die
empfangende Seite kann dann entscheiden, was sie damit tut, statt nichts von
ihnen zu wissen.

**CSV und Maltego** tragen denselben Feldsatz; die Maltego-Variante verwendet
die Spaltennamen, die der Maltego-Import erwartet, sodass sie ohne Handarbeit
auf Entitäten und Verbindungen abgebildet wird.

## Was exportiert wird

Dieselbe Auswahlregel, die auch der Bericht verwendet:

* Ist irgendetwas im Fall als **relevant** markiert, enthält der Export genau
  diese Funde.
* Andernfalls enthält er alles, was nicht als Fehltreffer markiert ist.

Der Export folgt also Ihrer Triage. Wollen Sie das Gesamtbild, entfernen Sie
zuvor die Relevanzmarkierungen; wollen Sie den Fall so, wie Sie ihn bewertet
haben, lassen Sie sie stehen.

## Vor dem Versand

1. Prüfen Sie die Bewertung dessen, was Sie versenden — siehe
   [Funde bewerten](12-assessing-findings.md). Bewertung **F** heisst, die
   Quelle wurde nie eingestuft; das kann die empfangende Analystin nicht
   wissen, wenn Sie es nicht dazusagen.
2. Überlegen Sie, ob **alles** in der Datei in fremde Hände gehört. Der Export
   enthält, was Ihr Fall enthält — auch Notizen.
3. Denken Sie daran, dass die empfangende Seite keinen Zugriff auf Ihren Fall
   hat. Was Sie senden, ist alles, was sie je davon sehen wird — deshalb
   leisten die Provenienzfelder echte Arbeit.

Siehe auch: [Berichte](08-reports.md) · [Funde bewerten](12-assessing-findings.md)
