# Lavorare con i casi

Ogni indagine vive in un **caso**. Tutti i risultati di ricerca sono
collegati a un caso, per cui il primo passo è sempre averne uno aperto.

## Creare un caso

1. Vada su **Casi** e clicchi su **"Nuovo caso"** (in alto a destra).
2. Compili:
   - **"Titolo"** (obbligatorio) — un nome breve per l'indagine.
   - **"Priorità"** — *Normale*, *Alta* o *Urgente* (predefinito *Normale*).
3. Confermi. Il caso riceve automaticamente un **numero del caso**.

> Può anche creare un caso al volo dal modulo di ricerca con il pulsante
> **"Nuovo"** accanto ad *"Assegna al caso"*.

Una **descrizione** non è prevista nella finestra di creazione — la
aggiunga in seguito tramite **"Modifica"** all'interno del caso.

## L'elenco dei casi

La tabella **Casi** mostra **"Numero del caso"**, **"Titolo"**,
**"Stato"**, **"Priorità"** e **"Creato"**. Clicchi su una riga per
aprirla.

Con un **clic destro** su una riga ottiene azioni rapide: *"Apri caso"*,
*"Copia numero del caso"*, *"Copia ID"* e (solo amministratori)
*"Elimina"*.

## All'interno di un caso

L'intestazione del caso mostra il numero del caso, il titolo e i
contrassegni di stato/priorità, oltre ai pulsanti:

- **"Report PDF"** — un rapporto scritto sul caso (vedi [Rapporti](08-reports.md)).
- **"Esporta"** — lo stesso caso in formato CSV, Maltego, MISP o STIX
  ([Esportare](14-exporting.md)).
- **"Modifica"** — modificare titolo, **descrizione**, stato (*Aperto / In
  corso / Chiuso / Archiviato*), priorità o **"Assegnato a"**.
- **"Elimina"** — solo amministratori.

Sotto l'intestazione si trovano le schede del caso:

1. **"Risultati"** — i risultati come elenco di lavoro, ordinati per
   rilevanza ([come vengono valutati i risultati](12-assessing-findings.md)).
   È la scheda da cui iniziare.
2. **"Grafico di rete"** — la mappa visiva di tutto ciò che è stato
   trovato ([come leggerla](06-reading-the-graph.md)).
3. **"Mappa"** — ogni risultato dotato di coordinate, rappresentato
   geograficamente, con una cronologia a lato. Utile solo quando un caso
   contiene risultati localizzati (luoghi, recensioni, immagini
   georeferenziate).
4. **"Elenco (N)"** — le stesse entità come tabella ricercabile e
   ordinabile.
5. **"Novità dall'ultima esecuzione"** — che cosa ha aggiunto la ricerca
   più recente ([seguire le variazioni](13-tracking-changes.md)).
6. **"Nuova ricerca"** — eseguire una ricerca i cui risultati confluiscono
   direttamente in questo caso ([come funziona la ricerca](03-searching.md)).

## Fare ordine nei risultati

Man mano che arrivano i risultati, vorrà separare il segnale dal rumore:

- **Segna come rilevante** — contrassegna un'entità chiave (stella dorata
  + alone nel grafo) affinché risalti e compaia in evidenza nei rapporti.
- **"Rimuovi come falso positivo"** — elimina un'entità e i suoi
  collegamenti dal caso quando si tratta chiaramente di rumore.

Entrambe le funzioni sono disponibili con un clic destro su un nodo, dal
pannello dei dettagli del nodo o dalla colonna *Azioni* della scheda
**Elenco**.

## Registro delle ricerche

La scheda **«Registro delle ricerche»** elenca ogni ricerca del caso: quando,
da chi, con quale termine e con quale **scopo / base legale**. Le ricerche
automatiche di un monitoraggio compaiono come *«Ricerca automatica»*. Il
registro si trova nell'archivio dati della Sua autorità; il gestore della
piattaforma non può leggerlo.

## Modelli di caso

Alla creazione di un caso può scegliere un **modello (tipo di reato)** —
ransomware, phishing, commercio darknet, sextortion ecc. È un punto di
partenza, non una regola:

- la **ricerca** del caso preseleziona il playbook adatto (moduli),
- il **rapporto** parte con una struttura adatta al tipo di reato,
- un'etichetta blu nell'intestazione del caso indica il modello; passandoci
  sopra elenca gli **strumenti tipici successivi**, un clic apre la ricerca.

Il modello può essere modificato o rimosso in qualsiasi momento tramite
**Modifica**.

## Casi limitati (need-to-know)

Per impostazione predefinita, tutte le persone della Sua autorità vedono tutti
i casi. Attivi **«Accesso»** alla creazione o modifica di un caso per
**limitarlo**: lo vedono allora solo **chi lo ha creato**, la **persona
assegnata**, i **membri** indicati e l'**amministrazione** della Sua autorità.
Per tutti gli altri il caso non esiste — manca da elenchi, ricerche, avvisi e
monitoraggi, e il suo link risponde «non trovato».

- Solo chi ha creato il caso, o l'amministrazione, può modificare l'accesso.
  I membri lavorano nel caso ma non possono allargare la cerchia.
- I membri sono nomi utente. Si possono aggiungere anche colleghi che non hanno
  mai effettuato l'accesso.
- Ogni modifica dell'accesso figura nel **«Registro delle ricerche»** del caso.
- L'amministrazione è inclusa di proposito: qualcuno deve poter riassegnare un
  caso quando l'inquirente non c'è più.

## Salvare le prove

Un risultato è un link — se la pagina viene cancellata, resta solo
l'affermazione. **«Salva pagina»** (nella scheda di un risultato con pagina di
origine, o nella scheda **«Prove»** per qualsiasi indirizzo digitato) carica la
pagina in un vero browser e deposita, nell'archivio della Sua autorità:

- uno **screenshot dell'intera pagina** (PNG),
- un **archivio** della pagina con immagini e formattazione (MHTML — si apre in
  Chrome o Edge),
- l'**impronta SHA-256** di ogni file, l'indirizzo finale dopo i
  reindirizzamenti, lo stato HTTP, l'ora, chi ha salvato e se è stato usato Tor.

Le pagine `.onion` vengono caricate tramite Tor e possono richiedere più di un
minuto. Gli indirizzi interni vengono rifiutati. L'impronta permette a
chiunque di verificare in seguito che un file scaricato è esattamente quello
salvato — su Windows: `certutil -hashfile file.mhtml SHA256`. Ogni salvataggio
figura anche nel **«Registro delle ricerche»**. Il gestore della piattaforma
conosce solo le impronte, mai la pagina.

---

Avanti: **[Eseguire una ricerca →](03-searching.md)** · Indietro: **[Primi passi](01-getting-started.md)**
