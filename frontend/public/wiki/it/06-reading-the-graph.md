# Leggere il grafo

La scheda **"Grafico di rete"** rappresenta tutto il contenuto di un caso
come una rete: i **nodi** sono entità (persone, account, canali,
indirizzi, messaggi, …) e gli **archi** sono le relazioni tra di esse. Il
**colore** del nodo indica il tipo di entità; la **dimensione** del nodo
cresce con il numero dei suoi collegamenti.

## Comandi (barra laterale sinistra)

- **"Layout"** — come vengono disposti i nodi: un albero in ampiezza
  (predefinito), *Force (fcose)*, *Concentrico*, *Cerchio*, *Griglia* o
  *Force (cose)*.
- **"Limite di rendering"** — i casi di grandi dimensioni possono
  contenere migliaia di nodi; questo limita quanti ne vengono disegnati
  contemporaneamente (100 per impostazione predefinita, fino a 1000). Il
  contrassegno mostra *visibili / totali*.
- **"Mostra tutte le etichette"** — mostra l'etichetta di ogni nodo invece
  che solo al passaggio del mouse.
- **"Filtra per tipo"** — funge anche da **legenda**: una voce colorata
  per ogni tipo di entità con il relativo numero. Tolga la spunta da un
  tipo per nasconderlo.
- **"Adatta"** inquadra tutto · **"Riorganizza"** riesegue l'animazione
  del layout · **"Screenshot"** scarica un PNG della vista corrente.
- In basso a destra i comandi di **zoom** (pulsanti + cursore, 10–400 %);
  anche la rotellina del mouse ingrandisce e riduce.

## Interagire con i nodi

- **Clic** su un nodo → si apre a destra il suo **pannello dei dettagli**.
- **Doppio clic** su un nodo → **"Espandi ricerca da qui"**: la
  piattaforma avvia una *nuova* ricerca a partire da quel nodo (p. es. un
  doppio clic su un canale Telegram lancia una ricerca sul canale), e i
  risultati confluiscono nello stesso caso.
- **Clic destro** su un nodo → un menu: *"Mostra dettagli"*, *"Espandi
  ricerca da qui"*, *"Segna come rilevante"* / *"Rimuovi marcatura"*,
  *"Aggiungi al monitoraggio…"*, *"Rimuovi come falso positivo"*, oltre a
  *"Copia etichetta"* / *"Copia ID entità"*.
- **Passi con il mouse** su un nodo per evidenziarlo insieme ai suoi
  collegamenti; passi su un arco evidenziato per leggerne l'**etichetta di
  relazione** (p. es. `MEMBER_OF`, `FORWARDED_FROM`). Gli archi sono
  orientati (punte di freccia).
- I nodi **rilevanti** ricevono un bordo dorato e un alone.

Grafo vuoto? *"Nessun dato — avvia una ricerca per costruire la rete"*.

## Il pannello dei dettagli del nodo

Selezionando un nodo vengono mostrati:

- Contrassegni nell'intestazione: il **tipo di entità**, la
  **piattaforma** (se presente), una percentuale di **confidenza** e un
  contrassegno dorato **★ rilevante** se il nodo è segnato.
- L'**etichetta** del nodo, un **URL** cliccabile se presente, poi una
  tabella con tutti i campi di dati restituiti dalla fonte (gli URL
  diventano link, gli hash compaiono con un pulsante di copia, gli elenchi
  vengono resi come punti elenco).
- Pulsanti d'azione: **"Attiva monitoraggio"**, segna/rimuovi come
  **rilevante** e **"Rimuovi come falso positivo"**.

## Leggere la qualità dal grafo

Due indizi visivi riportano la valutazione della piattaforma su un
risultato:

- **Un doppio anello** significa che due o più strumenti indipendenti
  hanno segnalato questo nodo. È il segnale più forte che il sistema
  produce. Si noti che la **dimensione** del nodo segue il numero di
  collegamenti, il che rende visivamente dominante la fonte più rumorosa —
  l'anello è il contrappeso, e contrassegna il nodo meglio *supportato*
  anziché quello più affollato.
- **Il contrassegno di valutazione** (p. es. `B2`) sulla scheda del nodo è
  la valutazione Admiralty: l'affidabilità della fonte come lettera, la
  credibilità di questa specifica affermazione come cifra.

Entrambi sono spiegati in dettaglio in [Valutare i risultati](12-assessing-findings.md) —
vale la pena leggerlo una volta, perché le valutazioni cambiano il modo in
cui dovrebbe stabilire le priorità.

La scheda del nodo dispone anche di un **campo nota**. Ciò che vi scrive
resta legato al risultato, confluisce nel rapporto e nell'esportazione, ed
è salvato nella banca dati della sua autorità. Lo usi per il ragionamento
che la valutazione non può cogliere: perché ritiene che questo account
appartenga alla stessa persona, che cosa ha già verificato, che cosa resta
da verificare.

## Lavorare sul caso

Un buon ritmo: esegua una ricerca → apra **Risultati** e lavori dall'alto
verso il basso (l'elenco è ordinato per rilevanza) → **clicchi** sui nodi
interessanti per leggere i dettagli e il link al riferimento → approfondisca
con la **Ricerca avanzata**, così da scegliere lei che cosa viene aggiunto
→ **segni come rilevanti** quelli che contano, **rimuova** i falsi positivi
e **annoti** il perché. Ripeta finché il quadro è completo, poi produca un
[rapporto](08-reports.md) o un'[esportazione](14-exporting.md).

Per un caso su cui ritorna, cominci invece da
**[Novità dall'ultima esecuzione](13-tracking-changes.md)**.

## Unire nodi

Quando due nodi indicano la stessa persona o cosa — due nomi utente di una
persona, due grafie di una ditta —, apra uno dei due e scelga **«Unisci…»**.
Scelga gli altri; confluiscono in quello aperto:

- i loro **collegamenti** vengono trasferiti (un collegamento che risulterebbe
  doppio diventa uno solo, con entrambe le fonti),
- le loro **fonti** contano per il nodo rimanente, il che può alzarne la
  valutazione,
- note e indirizzo di origine vengono ripresi, i loro nomi restano visibili come
  **«Noto anche come»**,
- le **ricerche future** che trovano un nome unito lo attribuiscono al nodo
  rimanente invece di ricrearlo,
- monitoraggi e avvisi seguono.

L'unione non è reversibile e figura nel **«Registro delle ricerche»**. Se vuole
solo registrare un collegamento senza decidere sull'identità, tracci invece un
collegamento.

## Stesso risultato in altri casi

Se un risultato di questo caso — un indirizzo e-mail, un nome utente, un
portafoglio — compare anche in un **altro caso della Sua autorità**, una barra
gialla sopra le schede lo segnala e la scheda del nodo mostra **«anche in
2026-…»**; un clic apre quel caso. Vengono citati solo i casi che Lei può
aprire: un caso limitato di cui non fa parte non compare mai qui. Il confronto
ignora maiuscole/minuscole e avviene nell'archivio della Sua autorità.

---

Avanti: **[Valutare i risultati →](12-assessing-findings.md)** · Indietro: **[Strumenti Telegram](05-telegram.md)**
