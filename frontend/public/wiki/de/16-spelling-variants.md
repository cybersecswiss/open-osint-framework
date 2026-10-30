# Schreibvarianten

Wer im Cybercrime ermittelt, sucht selten nach einem Menschen mit Namen. Man
sucht nach einem **Handle** — und Handles werden nicht zweimal gleich
geschrieben. Derselbe Akteur ist auf einem Forum `d4rkc1ph3r`, auf dem
nächsten `darkcipher`, auf dem dritten `dark_cipher`, und nach einer Sperre
`darkcipher1`.

Wer nur genau die eingegebene Zeichenkette sucht, verliert den Treffer schon
bei einem einzigen vertauschten Zeichen — ohne Meldung. Deshalb sucht die
Plattform Schreibvarianten mit.

## Was die Plattform jetzt mitsucht

| Muster | Beispiel |
|---|---|
| Leetspeak | `d4rkc1ph3r` ↔ `darkcipher` |
| Trennzeichen | `dark_cipher`, `dark.cipher`, `dark-cipher` |
| Angehängte Zahlen | `darkcipher1` → `darkcipher` |
| Kyrillisch → Lateinisch | `Пётр` → `petr` |

Diese Muster gelten in **beide Richtungen**: Wer `darkcipher` eingibt, findet
auch `d4rkc1ph3r`, und umgekehrt.

## Die wichtigste Regel: Kandidat ist nicht Identität

Ein Fund unter einer Variante bedeutet:

> Es gibt ein Konto, dessen Schreibweise zu Ihrer Suche passt.

Er bedeutet **nicht**:

> Das ist dieselbe Person.

`darkcipher` auf Reddit und `d4rkc1ph3r` auf XSS können zwei Menschen sein,
die beide dasselbe Wort mögen. Die Plattform hält das deshalb sichtbar
auseinander:

* Varianten-Funde tragen **`match_type: variant`** und nennen die Schreibweise,
  unter der sie gefunden wurden
* sie werden **niedriger bewertet** als ein direkter Treffer
* ihre Beziehung im Graphen heisst `possible_handle_variant` beziehungsweise
  `possible_account_of` — nicht `is_account_of`
* über der Fundliste steht ein Hinweis, wie viele Treffer aus Varianten stammen

**Was einen Kandidaten zu einem Fund macht, ist ein zweites Signal:** dasselbe
Passwort, derselbe PGP-Schlüssel, dasselbe Forum, dieselbe Wallet, dieselbe
Schreibweise im Text. Genau dafür gibt es die Kreuzbestätigung (siehe *Funde
bewerten*). Tragen Sie die Begründung ins Notizfeld am Knoten — im Bericht
steht sie später neben dem Fund.

## Wo es wirkt

**Automatisch, ohne Zusatzaufwand**

*Bekannte Akteure* (`threat_actor_check`) prüft Ihren Handle und seine
Varianten gegen einen Index von 830 000 Benutzernamen aus 25 Kriminalforen.
Der Index liegt lokal — die Variantensuche kostet nichts und dauert
Millisekunden.

**Auf Anforderung, weil es dauert**

*Handle-Sweep (Schreibvarianten)* im Modul **Alias** durchsucht rund 600
Plattformen — für jede Schreibweise einmal. Ein Lauf dauert deshalb ein bis
drei Minuten statt fünfzig Sekunden. Wählen Sie das Werkzeug bewusst aus, wenn
ein Handle im Zentrum eines Falls steht.

Der Nutzen ist erheblich: Im Test lieferte `d4rkc1ph3r` allein 8 Konten — mit
Varianten wurden daraus 54.

## Grenzen, die Sie kennen sollten

**Trennzeichen lassen sich entfernen, aber nicht erfinden.** `tony-stark`
findet `tonystark`. Umgekehrt nicht — die Plattform kann nicht wissen, dass
die Trennstelle nach `tony` gehört und nicht nach `to`. **Suchen Sie im
Zweifel die stärker getrennte Schreibweise**, die findet mehr.

**Kurze Handles bekommen keine Varianten.** Unter vier Zeichen wäre jeder
Treffer Rauschen: `b0b` für `bob` ist mit hoher Wahrscheinlichkeit ein anderer
Mensch.

**Die Zahl der Schreibweisen ist gedeckelt.** Der Handle-Sweep prüft höchstens
vier. Das ist Absicht — eine unbegrenzte Variantenliste erzeugt Kandidaten,
auf die kein Ermittler von selbst gekommen wäre, und genau dort entstehen
falsche Spuren.

## Namen von Personen

Bei Vor- und Nachnamen gilt eine andere Mechanik als bei Handles: Die
Sanktionsprüfung vergleicht **wortweise und
reihenfolgeunabhängig**. „Vladimir Putin" und „Putin Vladimir" liefern
dasselbe Ergebnis — vorher fiel je nach Eingabe eine der beiden amtlichen
Listen weg, weil die EU „Vladimir PUTIN" schreibt und die USA „PUTIN,
Vladimir". Unscharf ist die Prüfung dabei ausdrücklich nicht: Es werden
weiterhin nur **ganze Wörter** verglichen, damit niemand fälschlich auf einer
Sanktionsliste landet.
