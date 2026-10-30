# La funzione IA (collegamento assistito)

La **funzione IA** è un ausilio facoltativo, soggetto a licenza, che
esamina il grafo di un caso e **suggerisce** come i vari elementi
potrebbero essere collegati — cluster di identità ("questi account
sembrano appartenere alla stessa persona"), relazioni probabili tra nodi e
una breve valutazione con i passi successivi.

È **di supporto, mai automatica**. L'IA si limita a proporre; è *lei* a
decidere che cosa è vero e a confermare i collegamenti che condivide. Nulla
viene aggiunto al caso a sua insaputa.

> **Disponibilità.** Il pulsante compare solo se la sua autorità dispone
> della **licenza** per la funzione IA. Se non lo vede, la funzione non è
> attivata per il suo account — è normale.

## Utilizzo

1. Apra un caso che contiene alcuni risultati e vada al **Grafico di
   rete** (o al pannello IA del caso).
2. Clicchi su **"Collegamento IA"**. Viene avviato un job che gira in
   background — può continuare a lavorare; la pagina non viene bloccata.
3. Al termine riceve dei **suggerimenti**:
   - **Cluster di identità** — gruppi di nodi che il modello ritiene
     essere lo stesso attore.
   - **Collegamenti suggeriti** — archi proposti tra nodi, ciascuno con
     una breve motivazione.
   - Una breve **valutazione** e i **prossimi passi** da considerare.
4. **Esamini ogni suggerimento.** Applichi quelli che condivide
   (diventano archi reali nel grafo, contrassegnati come `source: ai`);
   ignori gli altri. Applicare di nuovo lo stesso suggerimento in seguito
   è innocuo — non crea doppioni.

## Che cosa vede l'IA (e che cosa no)

Per mantenere il più possibile i dati del caso entro il suo perimetro
sovrano, la piattaforma trasmette al modello solo la **struttura del
grafo** — tipi di nodo, etichette e indicazioni sintetiche — e **rimuove i
valori sensibili** prima che lascino il sistema (password, cookie, token,
hash, banner grezzi e credenziali in chiaro non vengono mai trasmessi). I
grandi blocchi di dati sono ridotti a brevi sintesi; gli identificatori
nascosti (un'e-mail/un numero di telefono/un handle isolato) vengono
mantenuti, perché sono proprio ciò che aiuta il collegamento.

> **Nota sulla sovranità.** Con il modello cloud predefinito (Gemini), il
> grafo ridotto lascia effettivamente la sua infrastruttura verso il
> fornitore. Per questo la funzione è **concessa in licenza per singola
> autorità e utilizzata con consenso**. Un modello interamente locale è
> l'alternativa sovrana prevista nella roadmap.

## Buone pratiche

- **Tratti i suggerimenti come piste, non come verdetti.** Verifichi un
  collegamento proposto sulla base degli elementi di prova sottostanti
  prima di farvi affidamento in un rapporto.
- **Prima metta a fuoco il caso.** Segnare i nodi chiaramente rilevanti e
  rimuovere i falsi positivi prima di eseguire l'IA le fornisce un input
  più pulito e suggerimenti migliori.
- **Casi di grandi dimensioni:** vengono analizzati solo i risultati più
  rilevanti (un numero limitato, stabilito dal suo gestore) — la nota
  dell'analisi indica quanti ne sono stati utilizzati e su quanti.

## Se non si avvia

- **"La funzione IA non è concessa in licenza per questa autorità."** — la funzione IA non è attivata per la sua autorità.
- **"quota / limite di richieste raggiunto"** — è stato raggiunto il limite di
  utilizzo del fornitore; il suo gestore deve aumentarlo (attivare la
  fatturazione) oppure attendere il ripristino.
- **"L'IA ha impiegato troppo tempo"** — un caso molto grande; il suo gestore può ridurre il
  limite di entità, oppure lei può mettere a fuoco il caso e riprovare.

Questi esiti vengono mostrati come un messaggio chiaro sul job, non come un
errore silenzioso.

---

Avanti: **[Monitoraggio e avvisi →](07-monitoring-and-alerts.md)** · Indietro: **[Leggere il grafo](06-reading-the-graph.md)**
