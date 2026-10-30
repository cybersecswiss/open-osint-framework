# Rapporti

Può trasformare qualsiasi caso in un **rapporto PDF** — utile per
l'incarto, per la trasmissione degli atti o per informare i colleghi.

## Generare un rapporto

1. Apra il caso e clicchi su **"Report PDF"** nell'intestazione (si apre
   la pagina **"Genera report PDF"**).
2. In **"Sezioni da includere"**, spunti le parti desiderate. Sezioni
   disponibili, nell'ordine in cui compaiono nel documento:
   - **"Copertina"** — logo, numero del caso, titolo, stato
   - **Riepilogo** — che cosa contiene il caso, suddiviso per tipo
   - **Risultati chiave** — i venti risultati meglio classificati *con il
     motivo della posizione di ciascuno*: quali strumenti lo hanno
     confermato e come è valutata la fonte. È la sezione che deve ricevere
     un lettore che ne legge una sola.
   - **Tabella delle entità** — tutti i risultati, ordinati per rilevanza
     anziché alfabeticamente
   - **Relazioni** — chi è collegato con chi, raggruppato per tipo, **con
     lo strumento che ha affermato ciascun collegamento**
   - **Grafo** — un'immagine della rete, con doppi anelli che
     contrassegnano i risultati segnalati da più di uno strumento
   - **Ricerche eseguite** — quali ricerche hanno prodotto questo caso
   - **Avvisi**
   - **Cronologia**
   - **Fonti** — l'appendice delle citazioni: URL della fonte, strumento, e
     quando la fonte ha fatto l'affermazione rispetto a quando è stata
     salvata

   Tutte sono preselezionate per impostazione predefinita; tolga la spunta
   da ciò che non le serve.

> **Il rapporto dichiara che cosa ha tralasciato.** Se nel caso qualcosa è
> segnato come rilevante, il rapporto contiene esattamente quei risultati;
> altrimenti contiene tutto ciò che non è segnato come falso positivo. In
> entrambi i casi indica quale regola è stata applicata e quanto è stato
> escluso — un rapporto filtrato che non dichiara di esserlo sarebbe
> peggiore di uno non filtrato. I segnaposto non vengono mai contati come
> risultati (vedi [Valutare i risultati](12-assessing-findings.md)).
3. Il rapporto viene redatto nella **lingua attuale dell'interfaccia**
   (*"Il report sarà reso in {lingua}…"*) — se ne desidera un'altra,
   cambi prima la lingua con il selettore nell'intestazione.
4. Clicchi su **"Genera PDF"**. Il file viene scaricato come
   `{case_number}.pdf` e compare il messaggio **"Report scaricato"**.

In caso di errore vedrà *"Generazione del report fallita"* — riprovi o
riduca le sezioni selezionate, e informi il suo gestore se il problema
persiste.

## Suggerimenti

- **Segni come rilevanti le entità chiave** prima della generazione — le
  entità contrassegnate risaltano nel rapporto.
- La **copertina** usa il **logo** e il nome visualizzato della sua
  organizzazione, che un amministratore imposta in **Admin →
  Impostazioni**.
- Generi un nuovo rapporto ogni volta che il caso è andato avanti; il PDF è
  un'istantanea a un dato momento, non un documento dinamico.

## Opzioni del rapporto

- **Solo i risultati contrassegnati come rilevanti (estratto)** — tabelle,
  grafico e pagine salvate mostrano solo i risultati contrassegnati con ★ e i
  collegamenti tra loro. Ogni pagina reca la dicitura *«Estratto»*. Senza la
  spunta il rapporto contiene tutti i risultati tranne quelli segnati come
  falsi positivi.
- **PDF o Word** — Word serve per rielaborare: stesso contenuto e stesse
  immagini, impaginazione più semplice.
- Due sezioni in più: **«Registro delle ricerche»** (chi ha cercato cosa,
  quando e con quale scopo) e **«Pagine salvate»** (screenshot con SHA-256,
  perché chi legge possa verificare un file scaricato).
- Un caso con **modello** parte con la struttura del suo tipo di reato.

---

Avanti: **[Riferimento e glossario →](09-reference.md)** · Indietro: **[Monitoraggio e avvisi](07-monitoring-and-alerts.md)**
