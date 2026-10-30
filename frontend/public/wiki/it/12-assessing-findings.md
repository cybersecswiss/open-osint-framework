# Valutare i risultati

Una ricerca su una dozzina di moduli restituisce abitualmente diverse
centinaia di nodi. La raccolta non è mai stata la parte difficile — lo è
decidere quali venti contano. Questa pagina spiega i tre meccanismi che la
piattaforma le mette a disposizione a tal fine e, altrettanto importante,
che cosa ciascuno di essi **non** afferma.

## La valutazione (Admiralty)

Ogni risultato reca una valutazione di due caratteri come **B2**. Si tratta
della scala Admiralty della NATO, che risponde a due domande distinte che un
unico valore di "confidenza" finiva per confondere.

**La lettera — quanto è affidabile la fonte?** Dichiarata per ogni
strumento, perché solo l'autore dello strumento sa quale tipo di
affermazione esso produce. Un risultato proveniente da un registro di
certificati è un fatto di natura diversa da un risultato su una pagina di
profilo estratta dal web, anche quando entrambi hanno "funzionato".

| | Significato |
|---|---|
| **A** | Completamente affidabile — registro ufficiale o documento primario |
| **B** | Generalmente affidabile |
| **C** | Abbastanza affidabile |
| **D** | Generalmente non affidabile |
| **E** | Non affidabile |
| **F** | **Non valutabile** — lo strumento non dichiara nulla |

**F è una lacuna dichiarata onestamente, non un cattivo voto.** Significa
che nessuno ha valutato quella fonte, per cui non va letta come "prova
debole" — va letta come "non valutata".

**La cifra — quanto è credibile questa specifica affermazione?** Ricavata
dalla piattaforma per ogni risultato, perché solo la piattaforma può vedere
se altri strumenti concordano.

| | Significato |
|---|---|
| **1** | Confermato da altre fonti — **due o più strumenti indipendenti hanno segnalato la stessa cosa** |
| **2** | Probabilmente vero |
| **3** | Possibilmente vero |
| **4** | Dubbio |
| **6** | Non valutabile |

**5 ("improbabile") non viene mai assegnato.** Nulla nella catena di
raccolta può giustificare un argomento attivo contro un risultato, per cui
la piattaforma non finge di poterlo fare.

Una sottigliezza da conoscere: quando più strumenti segnalano lo stesso
nodo, la lettera mostrata è la **migliore** affidabilità tra di essi. Se un
registro e uno scraper restituiscono entrambi un valore, il risultato vale
quanto la parola del registro — una seconda fonte debole può aumentare la
credibilità, ma non può ridurre l'affidabilità.

## Conferma incrociata

Sotto la valutazione vede gli strumenti che hanno segnalato in modo
indipendente lo stesso risultato, p. es. **✓ 3**. Passi con il mouse per
vedere quali.

È il segnale più forte che il sistema produce, ed è il motivo per cui la
cifra può raggiungere **1**. Due proprietà lo rendono affidabile:

* Si basa sull'**identità canonica** del risultato, non sulla grafia
  esatta — due modi di scrivere lo stesso indirizzo contano comunque come
  concordanza.
* Si **accumula da una ricerca all'altra**. Uno strumento che conferma un
  nodo mesi dopo viene aggiunto all'elenco invece di sostituirlo. È proprio
  questa cronologia la parte che vale la pena conservare.

Nel grafo, un nodo segnalato da due o più strumenti indipendenti è disegnato
con un **doppio anello**. La dimensione del nodo segue il numero dei suoi
collegamenti, il che rende visivamente dominante la fonte più rumorosa;
l'anello è il contrappeso, e contrassegna il risultato meglio supportato
anziché quello più affollato.

## Classificazione per rilevanza

L'elenco dei risultati è ordinato secondo un punteggio di rilevanza
costruito su quattro segnali:

| Segnale | Peso | Perché |
|---|---|---|
| Conferma incrociata | 40 % | La concordanza indipendente è il segnale più difficile da falsificare |
| Affidabilità della fonte | 25 % | La lettera Admiralty |
| Posizione nel grafo | 20 % | Quanto è collegato il nodo |
| Distanza dal suo selettore | 15 % | Passi dall'elemento che ha effettivamente cercato |

Il punteggio è **ricalcolato ogni volta, mai salvato**. Segni un falso
positivo o esegua un altro strumento e l'ordine cambia immediatamente. Una
colonna salvata sarebbe superata già dal clic successivo, e lei non avrebbe
modo di capire quali righe sono aggiornate.

Il rapporto utilizza lo stesso punteggio nello stesso modo, per cui l'ordine
che vede sullo schermo è l'ordine in cui argomenta il PDF. Nel sistema
esiste deliberatamente una sola classificazione.

## Riferimenti probatori

Quando uno strumento ha indicato una fonte, il risultato reca un **link al
riferimento** — la pagina da cui proviene l'affermazione — oltre al momento
in cui la fonte l'ha espressa (`observed`), distinto dal momento in cui è
stata salvata nel suo caso (`found`). Per le fonti in rapida evoluzione,
come i siti di leak, i paste e Telegram, è il momento dell'osservazione
quello che conta a fini probatori.

> **I risultati meno recenti possono non avere un link al riferimento.**
> Una colonna può essere compilata solo da uno strumento che restituisce il
> valore, per cui le righe raccolte prima che la sua istanza supportasse la
> provenienza restano vuote finché quella fonte non viene nuovamente
> scansionata. Si tratta di una lacuna nella documentazione, non di un
> errore nel risultato — e ripetere la ricerca la colma senza creare
> doppioni.

## I segnaposto non sono risultati

Alcuni nodi esistono solo per mantenere il grafo connesso: è stata segnalata
una relazione la cui altra estremità non è mai stata confermata di per sé.
Questi nodi sono contrassegnati come segnaposto, vengono conteggiati a parte
e non compaiono mai nei rapporti né nelle esportazioni. Nessuno li ha
affermati, per cui non costituiscono prova di nulla.

L'unica eccezione è il nodo del termine che ha cercato. Tecnicamente è
virtuale, ma è il selettore oggetto d'indagine e fa da ancoraggio alla
maggior parte del grafo, per cui viene trattato ovunque come reale.

## Che cosa fare con tutto questo

Un ordine di lavoro pratico:

1. Ordini per rilevanza (l'impostazione predefinita) e legga per prima la
   parte alta dell'elenco.
2. Privilegi i risultati con una **cifra 1** — sono quelli sostenuti da più
   di uno strumento.
3. Apra il link al riferimento prima di fare affidamento su qualsiasi cosa.
   La valutazione le dice quanto peso merita una fonte; non le dice mai che
   il risultato è vero.
4. Segni come rilevante ciò che conta (la stella) e segni come tali i falsi
   positivi. Entrambe le cose si riflettono direttamente sulla
   classificazione e su ciò che contiene il rapporto.
5. Annoti il *perché* nel campo nota del nodo. La valutazione è quella della
   piattaforma; la nota è la sua, ed è quella che avrà ancora senso fra sei
   mesi.

Vedi anche: [Leggere il grafo](06-reading-the-graph.md) ·
[Rapporti](08-reports.md) · [Esportare](14-exporting.md)
