# Eseguire una ricerca

La ricerca è il flusso di lavoro centrale: lei fornisce alla piattaforma un
**indicatore** (un nome utente, un'e-mail, un dominio, un IP, un numero di
telefono, un indirizzo crypto, un handle Telegram, …), la piattaforma esegue
i **moduli** pertinenti e i risultati alimentano il grafo del caso.

Può cercare dalla pagina **Ricerca** oppure dalla scheda **"Nuova ricerca"**
all'interno di un caso. All'interno di un caso i risultati aggiornano il
grafo sul posto; dalla pagina autonoma ottiene un URL di avanzamento che può
salvare tra i preferiti.

## Da dove cominciare: la pagina "Situazione"

Se non dispone ancora di un selettore, apra **Situazione** nel menu. La
pagina elenca ambiti di reato tratti da rapporti di situazione pubblici — il
rapporto annuale di fedpol, *Sicherheit Schweiz* del SIC, Europol — e ogni
scheda indica la sua fonte e la sua data.

Clicchi su **"Riprendi"** accanto a un tema e il modulo di ricerca si apre
precompilato con il termine e con restrizioni sensate (p. es.
*Rockerkriminalität* + *Schweiz*). Nulla viene eseguito finché non preme
**Avvia ricerca** — prima può modificare il termine, le restrizioni e i
moduli.

> **Che cosa è il catalogo, e che cosa non è.** Descrive *ambiti di reato*,
> non sospettati. Non designa alcuna organizzazione come minaccia e non
> fonda alcun sospetto; ogni affermazione appartiene alla fonte citata, non
> a questo strumento. Le voci sono punti di partenza per la ricerca.

Il catalogo è un file (`threat-catalog/catalog.json`) che i suoi
amministratori possono ampliare o correggere in qualsiasi momento — senza
bisogno di un aggiornamento del software. Si rivolga a loro se manca un
ambito di reato rilevante per il suo lavoro.

## Passo per passo

1. **"Termine di ricerca / Indicatore"** — digiti l'elemento su cui sta
   indagando. Il testo segnaposto ne dà un'idea: *"es. anonymous99,
   max@example.com, 1.2.3.4, example.com, sha256:…"*.
2. **"Tipo"** — scelga come va interpretato il termine (Nome utente,
   E-mail, Dominio, IP, URL, Hash, Telefono, indirizzo Bitcoin/Ethereum, i
   tipi Telegram, invito Discord, **URL immagine**, Telefono o Parola
   chiave). È la scelta decisiva — stabilisce quali moduli possono essere
   eseguiti. L'elenco completo si trova nel
   [Riferimento](09-reference.md#query-types).
3. **"Assegna al caso"** — scelga il caso (o clicchi su **"Nuovo"** per
   crearne uno). All'interno di un caso questo campo è già impostato.
4. **"Moduli"** — spunti i collettori da eseguire. **Sono mostrati solo i
   moduli che comprendono il tipo scelto**, e vengono selezionati
   automaticamente quando cambia il tipo. Passi con il mouse su un modulo
   per vedere quali dei suoi strumenti verranno eseguiti. Se nessun modulo
   supporta il tipo, vedrà *"Nessun modulo disponibile per il tipo …"*.
5. Clicchi su **"Avvia ricerca"** (il pulsante diventa *"Ricerca in
   corso..."*).

### Playbook — partire dal reato anziché dall'elenco dei moduli

Sopra le caselle dei moduli trova i **playbook**: preimpostazioni per i tipi
di reato più comuni — ransomware, phishing, commercio darknet, frode /
negozio falso, frode cripto, sextortion, infrastruttura. Sceglierne uno
spunta i moduli che vale la pena eseguire per quel tipo di caso.

Sono pura configurazione: un playbook non fa nulla che lei non potrebbe fare
a mano, le risparmia solo di decidere quali tra una dozzina di moduli
meritano il loro tempo di esecuzione. Due dettagli li rendono affidabili:

* Vede solo i playbook per cui la sua autorità dispone di una licenza — una
  preimpostazione non può mai proporre un modulo che verrebbe poi rifiutato.
* Ogni voce indica se si adatta al **tipo** attualmente selezionato, così
  una preimpostazione pensata per i domini non viene proposta per un nome
  utente.

Può modificare le spunte in seguito. Il playbook è un punto di partenza, non
un'impostazione.

## Ricerca avanzata: guardare prima di acquisire

La ricerca ordinaria aggiunge al caso tutto ciò che trova. È quello che
serve quando si apre una pista, ed è la cosa sbagliata quando se ne segue
una — un solo pivot troppo ampio può seppellire un caso nel rumore.

La **Ricerca avanzata** (il pannello *Ricerca avanzata*, raggiungibile
anche da qualsiasi nodo del grafo) esegue la stessa raccolta ma **non salva
nulla**. Riceve i candidati come anteprima, con quelli già presenti nel
caso contrassegnati, e spunta quelli da tenere. Solo questi vengono
registrati.

È una scelta deliberata, e non solo per ordine: **la decisione di
collegare un risultato a un altro spetta a una persona.** La piattaforma le
mostrerà che un nome utente compare su undici siti; non deciderà al posto
suo che si tratta della stessa persona. In un incarto processuale è proprio
questa distinzione che deve reggere.

La usi ogni volta che parte da un risultato anziché da un selettore nuovo —
il che, dopo la prima ricerca, accade quasi sempre.

> **Campi facoltativi.** *"Email (facoltativa)"*, *"Telefono
> (facoltativo)"*, *"Priorità (facoltativa)"* e *"Nota (facoltativa)"*
> sono comodità: la nota viene aggiunta alla descrizione del caso con data,
> ora e il suo nome. La ricerca stessa usa solo il campo principale
> *"Termine di ricerca / Indicatore"*.

## Restringere una ricerca per parola chiave ("Restringi")

Un termine come **Crimson Wolves** restituisce risultati da tutto il mondo.
Quando il tipo di ricerca è **Parola chiave (forum/darknet/paste)**, compare
un campo **"Restringi (facoltativo)"** in cui può scegliere — o digitare
liberamente — termini di restrizione:

* **Regione** — Schweiz, Deutschschweiz, Romandie, Ticino
* **Cantone** — tutti i 26, con il loro nome ufficiale (Zürich, Genève, Ticino …)
* **Internazionale** — Europa, International, Paesi confinanti
* **Ambito di reato** — Drogenhandel (traffico di stupefacenti),
  Waffenhandel (traffico d'armi), Geldwäscherei (riciclaggio di denaro) …
* **qualsiasi termine che digita lei stesso** — una città, un quartiere, un
  ambiente

Ogni termine di restrizione avvia **un'ulteriore esecuzione di ricerca**
con quel termine aggiunto. "Crimson Wolves" più "Schweiz" e "Zürich" esegue
tre ricerche: il termine semplice, `Crimson Wolves Schweiz` e
`Crimson Wolves Zürich`. Il campo indica quante esecuzioni costerà la sua
selezione *prima* che lei avvii la ricerca.

Tutti i risultati confluiscono nello **stesso caso**. Nel grafo vedrà il
termine di base diramarsi verso quelli ristretti, così potrà capire **quale
restrizione ha prodotto quale risultato**. I servizi trovati da più di
un'esecuzione compaiono una sola volta, non più volte.

> **Perché il limite di cinque?** Ogni esecuzione interroga ogni strumento
> di ogni modulo selezionato. Cinque termini di restrizione su quattro
> strumenti fanno già due dozzine di richieste, e diverse fonti ci limitano
> a quel volume. Pochi termini di restrizione ben scelti danno risultati
> migliori di molti termini generici.

> La restrizione si applica solo alle ricerche per **parola chiave**.
> Aggiungere "Zürich" a un indirizzo e-mail o a un indirizzo Bitcoin
> produrrebbe un selettore che non trova nulla, per cui il campo è nascosto
> per quei tipi.

## Scopo / base legale

Il campo **«Scopo / base legale»** registra il motivo di una ricerca —
numero d'incarto, decreto, mandato. Viene salvato **solo nel registro delle
ricerche della Sua autorità** (scheda **«Registro delle ricerche»** del caso),
mai presso il gestore della piattaforma, che viene a sapere soltanto *che* è
stato indicato uno scopo.

- All'interno di un caso viene riproposto l'ultimo scopo utilizzato.
- Se la Sua amministrazione ha attivato *«Richiedere uno scopo per ogni
  ricerca»* (Admin → Impostazioni), una ricerca senza scopo viene rifiutata.
  Se in quel momento il registro delle ricerche della Sua autorità non è
  raggiungibile, la ricerca **non viene avviata** — ciò che non può essere
  registrato non viene eseguito.
- Lo stesso vale quando crea un **monitoraggio**; le sue ricerche automatiche
  rimandano allo scopo indicato alla creazione.

## Seguire l'avanzamento

La ricerca si distribuisce **in parallelo** su tutti gli strumenti
pertinenti. Una tabella **"Stato degli strumenti"** in tempo reale si
aggiorna ogni 3 secondi con una riga per strumento:

**Modulo · Strumento · Stato · Risultati · Connessioni · Durata · Errori**

Termina come **"Completata"**, **"Completata (parziale)"** (uno strumento
ha incontrato un errore — p. es. una chiave API mancante), **"Ricerca
fallita"** oppure **"Interrotta"** (l'ha fermata lei — vedi sotto). Sulla
pagina di avanzamento autonoma ottiene inoltre i contatori **"Entità
trovate"** e **"Connessioni"** e un pulsante **"Apri il caso"**.

### Interrompere una ricerca

Se una ricerca dura troppo o ha digitato il selettore sbagliato, la
interrompa dalla pagina di avanzamento con **"Interrompi ricerca"**.

> **Tutto ciò che è stato trovato finora resta.** I risultati vengono
> registrati nel caso man mano che arrivano — l'interruzione ferma solo gli
> strumenti ancora in esecuzione. La barra di avanzamento resta quindi al
> punto effettivamente raggiunto dalla ricerca e deliberatamente **non**
> mostra 100 %: "interrotta" non è "completata", e un incarto deve mantenere
> leggibile questa differenza.
>
> **Uno strumento può proseguire brevemente.** L'interruzione pone fine
> alla nostra attesa della fonte; il modulo se ne accorge al passo
> successivo. È innocuo — ciò che arriva dopo appartiene a una ricerca
> conclusa e non viene più acquisito.

> **La barra di avanzamento riflette il lavoro reale** — si riempie man
> mano che ogni strumento termina (p. es. *7 di 11 strumenti completati*),
> non secondo una stima fissa.
>
> **I risultati vengono salvati man mano che arrivano.** I risultati sono
> registrati nel caso **progressivamente, modulo per modulo** — il grafo si
> riempie durante la ricerca, non deve attendere lo strumento più lento.
>
> **Può allontanarsi.** La ricerca viene eseguita sul server, per cui
> cambiare scheda, navigare altrove o **ricaricare il browser** non la
> ferma né fa perdere l'avanzamento — riapra il caso (o l'URL di
> avanzamento) e la ricerca è ancora lì, in aggiornamento.

> **Uno strumento con la nota "chiave non impostata" non è un errore** —
> quella singola fonte richiede semplicemente una chiave API che il suo
> gestore non ha configurato. Tutti gli altri strumenti sono stati
> eseguiti. Allo stesso modo, **zero risultati è una risposta valida**
> (p. es. un'e-mail che non compare in alcuna violazione di dati).

## Che cosa ottiene

Ogni risultato diventa un'**entità** (un nodo) nel caso, e le relazioni tra
di esse diventano **archi**. I moduli riusciti conservano i loro risultati
anche se un altro modulo ha generato un errore. Passi alla scheda
**"Grafico di rete"** per esplorare ciò che è stato restituito.

## Notizie & RSS

**Notizie & RSS** nel menu è la ricerca ordinaria con il modulo notizie
preselezionato. Esegue una ricerca a testo integrale nei feed gestiti dal
suo gestore — enti federali, polizia, media e fonti cyber — e restituisce
ogni risultato come nodo con **data, fonte e tipo di fonte**.

Il tipo di fonte conta quando legge il grafo: un comunicato `authority` e
un articolo `media` sono entrambe piste legittime, ma non hanno lo stesso
peso probatorio. Alle fonti ufficiali è inoltre attribuita una confidenza
più elevata.

Anche qui funziona la restrizione, per cui *Rockerkriminalität* +
*Schweiz* cerca nei feed entrambi i termini insieme. E poiché il modulo
notizie reagisce alle semplici parole chiave, un tema ripreso dalla pagina
**Situazione** cerca anche nelle fonti di notizie, senza alcun passaggio
supplementare.

> **Che cosa non fa.** Cerca nelle voci che un feed pubblica — titolo e
> sommario — non nel testo integrale dei PDF collegati. Inoltre i feed
> risalgono indietro nel tempo solo quanto la fonte li pubblica
> (tipicamente qualche anno). Un risultato mancante significa "non presente
> in questi feed", mai "non è successo".

Manca una fonte? Il suo gestore la aggiunge in **Impostazioni → Feed RSS**
nella console Admin globale; vale dalla ricerca successiva.

---

Avanti: **[Moduli e strumenti →](04-modules-and-tools.md)** · Indietro: **[Lavorare con i casi](02-cases.md)**
