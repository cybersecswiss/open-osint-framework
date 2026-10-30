# Aziende & persone

Tutti gli altri moduli partono da un selettore tecnico — un nome utente, un
dominio, un hash, un wallet. Questo parte da un **nome**, che è il punto
d'ingresso di cui dispone concretamente un caso di approvvigionamento, di
elusione delle sanzioni o di società di comodo.

Scelga il tipo di query **Ragione sociale** o **Nome di persona**, digiti il
nome e spunti il modulo *Aziende & persone*. Tutti e cinque gli strumenti
funzionano senza chiave.

## A che cosa risponde ciascuno strumento

| Strumento | La domanda a cui risponde | Valutazione |
|---|---|---|
| **Registro svizzero (FUSC)** | Questa azienda esiste in Svizzera, chi firma per essa, da quale indirizzo, ed è ancora iscritta? | A |
| **Struttura del gruppo (GLEIF)** | Chi la possiede, che cosa possiede, e sotto quali altri nomi è registrata? | A |
| **Verifica sanzioni** | Questo nome figura nelle liste di sanzioni dell'UE o degli Stati Uniti, e nell'ambito di quale programma? | A |
| **Collegamenti Wikidata** | Chi la dirige, chi detiene una partecipazione, che cos'altro appartiene allo stesso gruppo? | C |
| **Elenco svizzero** | Dove risponde fisicamente al telefono? | B |

## Un esempio pratico

Supponiamo che cerchi la società (fittizia) **Muster Trading SA** come
*Ragione sociale*. Una tale ricerca restituisce tipicamente:

* la **succursale di Ginevra** dal registro svizzero — il suo IDI (`CHE-…`),
  l'indirizzo, il registro cantonale in cui è iscritta e, se del caso, la
  data della **cancellazione** e il motivo;
* i **firmatari nominativamente indicati**, per esempio un direttore con
  firma individuale, con la nazionalità e il luogo di domicilio dichiarati,
  e la **frase esatta** pubblicata dal registro;
* il **gruppo**: la società madre estera con il suo LEI, i suoi nomi in
  altre scritture e varianti in caratteri latini, e le sue filiali;
* la **direzione** e le partecipazioni da Wikidata.

Si tratta di quattro tipi diversi di documentazione su un'unica
organizzazione, riuniti in un solo grafo — e ciascuno di essi reca il link
da cui proviene.

## Leggere i risultati con attenzione

**L'azienda è un dato di registro. Le persone sono estratte dalla prosa.** Le
pubblicazioni del registro svizzero indicano gli organi in una frase
standardizzata ("Signature individuelle a été conférée à …", "…, von Zug, in
Bern, Mitglied des Verwaltungsrates"), non in un campo strutturato. Lo
strumento le estrae in modo prudente e allega la **frase esatta** a ogni
persona che produce, sotto `register_statement`. Legga quella frase prima di
fare affidamento sul nome. È anche il motivo per cui le persone risultano con
una confidenza inferiore rispetto all'azienda a cui appartengono.

**Un "nessun riscontro" nelle sanzioni non è un nulla osta.** Il confronto è
deliberatamente esatto: ogni parola della sua query deve comparire nel nome
elencato. Ciò evita di accusare la persona sbagliata, e significa che una
grafia **traslitterata in modo diverso** non verrà trovata. Иванов e
Ivanov non vengono associati l'uno all'altro dalla macchina — quella
deduzione spetta a lei, così come la sua documentazione. Lo strumento
indica sempre quanti nomi ha verificato.

**Wikidata è una pista, non un dato di registro.** È gestito da una
comunità. Lo usi per trovare *dove cercare* — una filiale, un presidente, un
proprietario — e confermi poi quel risultato in un registro.

**Una voce mancante nell'elenco non prova nulla.** Un numero non iscritto è
assente da tel.search.ch esattamente come un numero inesistente.

## Dove si inserisce in un caso

L'ordine naturale:

1. **Prima il registro** — le fornisce l'entità giuridica, l'indirizzo e le
   persone, tutti citabili.
2. **Struttura del gruppo** — la società madre e le società sorelle sono di
   solito il luogo in cui si trova la vera controparte.
3. **Verifica sanzioni** su ogni nome prodotto dai primi due passi, non
   soltanto su quello da cui è partito.
4. **Poi il pivot tecnico**: l'indirizzo e le persone alimentano
   [ricerche ordinarie](03-searching.md) — il dominio dell'azienda in `infra`
   e `theharvester`, il nome di un organo negli strumenti alias, il numero di
   telefono negli strumenti di messaggistica.

Il playbook **Elusione delle sanzioni / approvvigionamento** imposta tutto
questo con un clic.

## Una parola sulla prudenza

Da qui in poi lavora con **dati personali di persone reali**. Una persona
indicata come organo in un registro di commercio è un fatto pubblico. Che la
stessa persona sia coinvolta in un reato è un'affermazione — la sua, e una
che deve essere in grado di sostenere.

La piattaforma tiene deliberatamente separate le due cose: gli strumenti
raccolgono, una persona collega, e il campo nota del nodo è il luogo in cui
va il suo ragionamento. Lo usi. Fra sei mesi sarà l'unica traccia del
*perché* ha collegato due risultati, ed è esattamente ciò che un incarto deve
essere in grado di dimostrare.

Vedi anche: [Valutare i risultati](12-assessing-findings.md) ·
[Eseguire una ricerca](03-searching.md) · [Esportare un caso](14-exporting.md)
