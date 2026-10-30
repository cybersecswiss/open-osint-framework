# Esportare un caso

Accanto al pulsante del rapporto, **Esporta** offre quattro formati
leggibili da macchina. Usi il rapporto quando a leggerlo sarà una persona;
usi un'esportazione quando lo farà un *sistema* o l'analista di un'altra
autorità.

| Formato | Da usare per |
|---|---|
| **CSV** | Fogli di calcolo, la sua gestione dei casi, filtri rapidi |
| **CSV Maltego** | Importare il caso come grafo in Maltego |
| **Evento MISP** | Trasmettere indicatori a un CERT / una piattaforma di threat intelligence |
| **STIX 2.1** | Lo standard internazionale per lo scambio di informazioni sulle minacce informatiche |

## Che cosa accompagna un risultato

Tutti e quattro i formati riportano la provenienza, perché un risultato
senza la sua origine non costituisce un elemento di prova utilizzabile per
il destinatario:

* lo **strumento** che lo ha segnalato,
* ogni strumento che lo ha **confermato in modo indipendente**,
* la **valutazione Admiralty**,
* l'**URL della fonte**, se lo strumento ne ha fornito uno.

## Due regole che valgono per ogni esportazione

**I segnaposto non escono mai dall'edificio.** I nodi che esistono solo per
mantenere il grafo connesso vengono esclusi. Nessuno li ha affermati, e
un'autorità partner che li ricevesse non avrebbe modo di distinguerli dai
risultati confermati.

**Ogni esportazione viene registrata.** La traccia di audit documenta chi ha
esportato quale caso, quando, in quale formato, e un checksum SHA-256 del
contenuto esatto. Trasmettere risultati a un'altra autorità è proprio il
tipo di atto che un incarto deve poter provare in seguito — compresa la
prova che ciò che lei ha inviato è ciò che l'altra parte ha ricevuto.

## Comportamenti specifici dei formati da conoscere

**MISP: gli indicatori non sono attivati per impostazione predefinita.** Gli
attributi vengono inviati con `to_ids=false`, a meno che lei non abbia
segnato il risultato come rilevante. `to_ids=true` indica al sistema
destinatario di *bloccare o generare un allarme* su un indicatore — dati
OSINT non verificati non devono arrivare pronti a scattare nella rete di un
partner. Segnare un risultato come rilevante è la sua dichiarazione di
averlo verificato; è questo che cambia il flag.

**STIX: i risultati al di fuori del vocabolario standard vengono
dichiarati.** L'OSINT produce tipi di oggetti per i quali STIX non ha un
equivalente. Anziché scartarli silenziosamente o etichettarli in modo
errato, vengono trasmessi come `x-osint-entity` e il bundle contiene un
oggetto `note` che indica quanti ne sono stati trasmessi così. Il
destinatario può quindi decidere che cosa farne, invece di ignorarne
l'esistenza.

**CSV e CSV Maltego** contengono lo stesso insieme di campi; la variante
Maltego usa i nomi di colonna attesi dall'importazione di Maltego, così che
venga associata a entità e collegamenti senza lavoro manuale.

## Che cosa viene esportato

La stessa regola di selezione usata dal rapporto:

* Se nel caso qualcosa è segnato come **rilevante**, l'esportazione contiene
  esattamente quei risultati.
* Altrimenti contiene tutto ciò che non è segnato come falso positivo.

L'esportazione segue quindi la sua cernita. Se desidera il quadro completo,
rimuova prima i contrassegni di rilevanza; se desidera il caso così come lo
ha valutato, li lasci.

## Prima dell'invio

1. Verifichi la valutazione di ciò che invia — vedi
   [Valutare i risultati](12-assessing-findings.md). La valutazione **F**
   significa che la fonte non è mai stata valutata, cosa che l'analista
   destinatario non può sapere se lei non lo dice.
2. Consideri se **tutto** il contenuto del file debba finire nelle mani di
   altri. L'esportazione contiene ciò che contiene il suo caso, note
   comprese.
3. Tenga presente che il destinatario non ha accesso al suo caso. Ciò che
   lei invia è tutto ciò che ne vedrà mai, per cui i campi di provenienza
   svolgono un lavoro reale.

Vedi anche: [Rapporti](08-reports.md) · [Valutare i risultati](12-assessing-findings.md)
