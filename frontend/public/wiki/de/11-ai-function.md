# Die KI-Funktion (unterstütztes Verknüpfen)

Die **KI-Funktion** ist ein optionaler, lizenzierter Helfer: Sie betrachtet den
Graphen eines Falls und **schlägt vor**, wie die Teile zusammenhängen könnten
— Identitätscluster („diese Konten wirken wie dieselbe Person"), mögliche
Beziehungen zwischen Knoten sowie eine kurze Einordnung mit nächsten Schritten.

Sie ist **unterstützend, nie automatisch**. Die KI schlägt ausschliesslich vor;
*Sie* entscheiden, was zutrifft, und übernehmen die Verknüpfungen, denen Sie
zustimmen. Dem Fall wird nichts hinter Ihrem Rücken hinzugefügt.

> **Verfügbarkeit.** Die Schaltfläche erscheint nur, wenn Ihre Behörde für die
> KI-Funktion **lizenziert** ist. Sehen Sie sie nicht, ist sie für Ihr Konto
> nicht freigeschaltet — das ist so vorgesehen.

## Anwendung

1. Öffnen Sie einen Fall mit einigen Funden und gehen Sie zum
   **Netzwerkgraphen** (oder zum KI-Bereich des Falls).
2. Klicken Sie auf **„KI-Verknüpfung" / „Mit KI analysieren"**. Ein Auftrag
   startet und läuft im Hintergrund — Sie können weiterarbeiten, die Seite
   blockiert nicht.
3. Ist er fertig, erhalten Sie **Vorschläge**:
   - **Identitätscluster** — Gruppen von Knoten, die das Modell für denselben
     Akteur hält.
   - **Vorgeschlagene Verbindungen** — mögliche Kanten zwischen Knoten, jeweils
     mit kurzer Begründung.
   - Eine knappe **Einordnung** und **nächste Schritte** zum Abwägen.
4. **Prüfen Sie jeden Vorschlag.** Übernehmen Sie, wem Sie zustimmen (daraus
   werden echte Kanten im Graphen, gekennzeichnet mit `source: ai`);
   ignorieren Sie den Rest. Denselben Vorschlag später erneut zu übernehmen
   ist unschädlich — es entstehen keine Dubletten.

## Was die KI sieht (und was nicht)

Damit Falldaten so weit wie möglich innerhalb Ihrer Hoheitsgrenze bleiben,
sendet die Plattform dem Modell nur die **Graphstruktur** — Knotentypen,
Beschriftungen und knappe Hinweise — und **entfernt sensible Werte**, bevor
irgendetwas das Haus verlässt (Passwörter, Cookies, Token, Hashes, rohe
Banner und Klartext-Zugangsdaten werden nie gesendet). Grosse Datenblöcke
werden auf kurze Zusammenfassungen gekürzt; vergrabene Identifikatoren (eine
verstreute E-Mail-Adresse, Telefonnummer oder ein Handle) bleiben erhalten,
weil genau sie beim Verknüpfen helfen.

> **Hinweis zur Datenhoheit.** Mit dem voreingestellten Cloud-Modell (Gemini)
> verlässt der reduzierte Graph Ihre Infrastruktur in Richtung des Anbieters.
> Genau deshalb ist die Funktion **je Behörde lizenziert und wird mit
> Einwilligung genutzt**. Ein vollständig lokales Modell ist die souveräne
> Alternative auf der Roadmap.

## Gute Praxis

- **Behandeln Sie Vorschläge als Spuren, nicht als Urteile.** Prüfen Sie eine
  vorgeschlagene Verbindung gegen den zugrunde liegenden Beleg, bevor Sie sich
  in einem Bericht darauf stützen.
- **Fokussieren Sie den Fall zuerst.** Die eindeutig relevanten Knoten zu
  markieren und Fehltreffer zu entfernen, bevor die KI läuft, gibt ihr
  saubereren Eingang und bessere Vorschläge.
- **Grosse Fälle:** Es werden nur die relevantesten Funde analysiert (eine von
  Ihrem Betreiber gesetzte Obergrenze) — der Analysehinweis sagt Ihnen, wie
  viele von wie vielen verwendet wurden.

## Wenn sie nicht läuft

- **„nicht lizenziert"** — die KI-Funktion ist für Ihre Behörde nicht
  freigeschaltet.
- **„Kontingent / Ratenlimit erreicht"** — das Nutzungslimit des Anbieters
  wurde erreicht; Ihr Betreiber muss es anheben (Abrechnung aktivieren) oder
  die Zurücksetzung abwarten.
- **„hat zu lange gedauert"** — ein sehr grosser Fall; Ihr Betreiber kann die
  Entitätsgrenze senken, oder Sie fokussieren den Fall und versuchen es
  erneut.

Das wird jeweils als klare Meldung am Auftrag angezeigt, nicht als stiller
Fehlschlag.

---

Weiter: **[Überwachung & Alarme →](07-monitoring-and-alerts.md)** · Zurück: **[Den Graphen lesen](06-reading-the-graph.md)**
