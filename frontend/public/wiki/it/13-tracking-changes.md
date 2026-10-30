# Seguire le variazioni in un caso in corso

In un caso che rimane aperto per settimane, la domanda raramente è "che cosa
abbiamo" — è **"che cosa c'è di nuovo dall'ultima volta"**. Due funzioni
rispondono a questa domanda: la scheda *Novità dall'ultima esecuzione* per
una ricerca avviata da lei, e il monitoraggio per quelle che si eseguono da
sole.

## "Novità dall'ultima esecuzione"

Apra un caso e scelga la scheda **Novità dall'ultima esecuzione**. Mostra
che cosa ha aggiunto la ricerca più recente: nuovi risultati, nuove
relazioni e da quale esecuzione provengono.

La scheda esiste perché ripetere una ricerca è deliberatamente
*idempotente* — un risultato già presente nel caso conserva la sua identità
invece di essere aggiunto due volte. È il comportamento corretto, ed è anche
il motivo per cui una nuova scansione sembra non aver prodotto nulla. È in
questa vista che la differenza diventa visibile.

**Che cosa conta come nuovo.** Il limite è il momento in cui la ricerca è
stata avviata; tutto ciò che è stato salvato nel suo caso dopo quel momento
è un'aggiunta. Un risultato che esisteva già ed è stato semplicemente
riconfermato **non** compare. Conta più di quanto sembri: ogni nuova
scansione aggiorna la provenienza dei risultati esistenti, e contarli come
scoperte farebbe sembrare ogni esecuzione una svolta.

### Che cosa non le dice

**Le sparizioni non vengono rilevate, e la vista lo dichiara.**

Se una voce su un sito di leak scompare o un profilo viene eliminato, qui non
comparirà. Il motivo è di onestà più che tecnico: uno strumento che ha
semplicemente fallito e un takedown effettivo appaiono identici dall'interno
della piattaforma. Segnalare il secondo quando si trattava in realtà del
primo sarebbe peggio che non dire nulla — per cui la piattaforma non dice
nulla, e lo dichiara apertamente.

Se una sparizione è rilevante per il suo caso, il metodo corretto è quello
di sempre: conservare le prove quando le vede (screenshot, esportazione,
link al riferimento) anziché aspettarsi che lo strumento ne noti l'assenza
in seguito.

## Monitoraggio

Mentre la vista delle differenze risponde a "che cosa ha aggiunto la mia
ultima esecuzione", il monitoraggio risponde a "avvisami quando qualcosa
cambia mentre non sto guardando".

Imposti un monitoraggio su un caso e la piattaforma ripete la ricerca secondo
una pianificazione e genera un avviso quando il risultato cambia.
Configurazione e gestione sono descritte in
[Monitoraggio e avvisi](07-monitoring-and-alerts.md).

Le due funzioni si completano bene: il monitoraggio le dice *che* qualcosa si
è mosso, la vista delle differenze le mostra *che cosa*.

## Una routine pratica

Per un caso in fase di indagine attiva:

1. Ripeta la ricerca, oppure lasci che lo faccia il monitoraggio.
2. Apra **Novità dall'ultima esecuzione** — è la via più breve verso ciò che
   è cambiato.
3. Esamini le aggiunte dall'alto verso il basso; sono ordinate secondo lo
   stesso punteggio di rilevanza usato ovunque (vedi
   [Valutare i risultati](12-assessing-findings.md)).
4. Segni quelle che contano, annoti il perché e lasci stare il resto — rimane
   nel caso e non costa nulla.
5. Generi un rapporto quando le serve un'istantanea. Il rapporto descrive
   sempre il caso nel suo stato attuale, non solo le differenze.

> **Vale la pena ripetere una volta un vecchio caso, anche solo per questo.**
> I risultati raccolti prima che la sua istanza introducesse valutazioni e
> link ai riferimenti restano senza valutazione finché la loro fonte non viene
> interrogata di nuovo. Una sola nuova scansione li completa — senza creare
> doppioni, perché l'identità è stabile.
