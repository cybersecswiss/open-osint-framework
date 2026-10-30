# Piattaforma OSINT — Manuale utente

Benvenuti. Questo manuale spiega come svolgere indagini sulla piattaforma
OSINT: accedere, creare un caso, effettuare ricerche su più fonti di dati,
leggere il grafo delle relazioni, monitorare obiettivi nel tempo ed
esportare rapporti.

È destinato agli **inquirenti** (utenti finali). Installazione, server e
credenziali sono trattati separatamente nel manuale del gestore
(`docs/operations.en.md`).

## Indice

1. **[Primi passi](01-getting-started.md)** — accedere con l'indirizzo
   e-mail di servizio e orientarsi nell'applicazione.
2. **[Lavorare con i casi](02-cases.md)** — ogni indagine vive in un
   caso; come crearli e gestirli.
3. **[Eseguire una ricerca](03-searching.md)** — il flusso di lavoro
   centrale: scegliere un tipo di query, inserire un indicatore, selezionare
   i moduli, seguire l'avanzamento.
4. **[Moduli e strumenti](04-modules-and-tools.md)** — i moduli di
   raccolta e ogni strumento che contengono.
5. **[Strumenti Telegram (approfondito)](05-telegram.md)** — raccolta
   Telegram autenticata: scansione di canali, ricerche di utenti / numeri
   di telefono / posizioni.
6. **[Leggere il grafo](06-reading-the-graph.md)** — come esplorare le
   entità e le relazioni prodotte da una ricerca.
7. **[Valutare i risultati](12-assessing-findings.md)** — valutazioni,
   conferma incrociata, rilevanza e riferimenti: decidere quali tra
   diverse centinaia di risultati contano davvero.
8. **[Seguire le variazioni](13-tracking-changes.md)** — che cosa ha
   aggiunto una nuova esecuzione, e che cosa la piattaforma deliberatamente
   non può dirle.
9. **[La funzione IA](11-ai-function.md)** — collegamento assistito, dove
   è concesso in licenza.
10. **[Monitoraggio e avvisi](07-monitoring-and-alerts.md)** — sorvegliare
    un obiettivo ed essere avvisati quando qualcosa cambia.
11. **[Rapporti](08-reports.md)** — trasformare un caso in un rapporto
    condivisibile.
12. **[Esportare un caso](14-exporting.md)** — CSV, Maltego, MISP e
    STIX per trasmettere i risultati a un altro sistema o a un'altra
    autorità.
13. **[Riferimento e glossario](09-reference.md)** — tipi di query, tipi
    di entità, relazioni tra archi e risoluzione dei problemi.
14. **[Supporto e ticket](10-support.md)** — contattare il gestore.

## In un minuto

1. Apra l'URL della piattaforma e acceda con il suo **indirizzo e-mail di
   servizio**.
2. Crei un **caso** per la sua indagine.
3. Apra il caso ed esegua una **ricerca**: scelga un *tipo di query*
   (nome utente, e-mail, dominio, IP, telefono, canale Telegram, indirizzo
   crypto, …), digiti l'indicatore, spunti i **moduli** da eseguire e avvii.
4. I risultati appaiono come un **grafo** di entità e relazioni all'interno
   del caso. Clicchi su un nodo per i dettagli; con un doppio clic
   approfondisce (pivot).
5. Se lo desidera, imposti un **monitoraggio** su un obiettivo oppure
   esporti un **rapporto**.

> **I suoi dati restano suoi.** I dati d'indagine (casi, entità,
> risultati) sono salvati nel sistema della sua organizzazione. Il gestore
> della piattaforma fa funzionare il software ma non può leggere i dati
> dei suoi casi.

---

Cominci qui: **[Primi passi →](01-getting-started.md)**
