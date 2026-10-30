# Strumenti Telegram (approfondito)

Il modulo **Telegram (approfondito)** esegue una raccolta Telegram
*autenticata* tramite l'API ufficiale MTProto. Legge molto più
dell'anteprima web pubblica: cronologia completa dei messaggi, membri e
amministratori dei canali, inoltri, media, oltre a ricerche di utenti,
numeri di telefono e geolocalizzazione.

> **Disponibilità.** Questo modulo funziona solo se il suo gestore ha
> configurato una sessione Telegram attiva. Se è inattiva, ogni strumento
> restituisce nei risultati una chiara nota *"telegram module not
> authenticated"* invece di far fallire l'intera ricerca. Chieda al suo
> gestore di (ri)autenticare la sessione — vedi il manuale del gestore,
> *"Telegram deep scanner (module-telegram)"*.

## I sei strumenti

| Strumento | Tipo di query | Digiti la query come… |
|------|-----------|---------------------|
| `telegram_scan` | `Canale Telegram` | `@channel`, un link `t.me/…` oppure `+inviteHash` (più valori separati da virgola) |
| `telegram_channel_info` | `Canale Telegram` | `@channel` (più valori separati da virgola) |
| `telegram_search` | `Ricerca canali Telegram` | `@chan1,@chan2 :: keyword` |
| `telegram_user_lookup` | `Utente Telegram / ID` | `@user` oppure un ID numerico (più valori separati da virgola) |
| `telegram_phone_lookup` | `Numero di telefono` | Numeri E.164, p. es. `+41790000000` (più valori separati da virgola) |
| `telegram_geo` | `Geo Telegram (lat,long)` | `47.3769,8.5417` |

Poiché `telegram_scan` e `telegram_channel_info` rispondono entrambi al
tipo di query `Canale Telegram`, selezionare il modulo per una query su un
canale li esegue **entrambi** — ottiene la scansione completa *e* i
metadati del canale.

## Che cosa restituisce ciascuno strumento

**`telegram_scan`** — lo strumento di punta. Per ogni canale/gruppo/invito:
- il **canale** (titolo, descrizione, numero di membri, contrassegno di verifica)
- i **messaggi** (testo, data, visualizzazioni, inoltri, risposte, reazioni, geo)
- i **membri** e, su richiesta, gli **amministratori** con i loro ruoli
- i messaggi **fissati**
- i **media** (nome del file, dimensione; facoltativamente SHA-256 / hash
  percettivo / EXIF)
- gli **IOC** estratti dal testo dei messaggi (indirizzi crypto, e-mail,
  URL, numeri di telefono, @menzioni, #hashtag, link `t.me/`)
- le **fonti degli inoltri** come canali collegati

Costruisce un grafo connesso: i messaggi *nel* canale, gli autori che li
hanno *pubblicati*, i membri *del* canale, gli IOC *menzionati*, i media
*allegati* e gli inoltri *da* altri canali.

**`telegram_channel_info`** — metadati completi del canale (descrizione,
numero di utenti online, gruppo di discussione collegato, modalità lenta,
se i partecipanti sono visibili) più i **canali simili/consigliati**.

**`telegram_search`** — ricerca per parola chiave lato server nei canali
che lei indica. Sintassi: i canali a sinistra di `::`, la parola chiave a
destra: `@ransomwatch,@leakchannel :: bitcoin`.

**`telegram_user_lookup`** — profilo utente completo: biografia, stato
online / ultimo accesso, contrassegni bot/scam/fake/verificato/premium, e
le **chat in comune** con l'obiettivo (rispetto all'account di raccolta).

**`telegram_phone_lookup`** — verifica se un numero di telefono è presente
su Telegram e, in caso affermativo, risolve l'account. Fortemente limitato
nella frequenza — lo usi per singole ricerche, non per elenchi massivi. I
contatti importati vengono cancellati automaticamente in seguito.

**`telegram_geo`** — trova utenti/canali vicini a una coordinata che hanno
attivato la visibilità geografica, con la distanza in metri.

## Note operative

- **Una scansione può essere voluminosa.** Telegram limita i membri a
  ~10 000; il numero di messaggi per canale segue il limite configurato
  dal gestore.
- I **canali privati / accessibili solo su invito** richiedono
  `auto_join` (un'opzione del gestore) — altrimenti ottiene solo i
  metadati, con una nota chiara.
- Le **impostazioni sulla privacy** di un obiettivo possono nascondere il
  suo numero di telefono, l'ultimo accesso e le foto del profilo; quei
  campi semplicemente non compariranno.
- **Riferimento probatorio.** Ogni esecuzione Telegram viene registrata in
  un log di audit concatenato tramite hash e a prova di manomissione (lato
  gestore), che documenta chi/che cosa/quando della raccolta.
- **Protezione dei dati (autorità di perseguimento penale svizzere).** Il
  testo dei messaggi e, con l'hashing attivo, i media vengono raccolti così
  come sono. Limiti le scansioni a ciò che serve al caso.

---

Avanti: **[Leggere il grafo →](06-reading-the-graph.md)** · Indietro: **[Moduli e strumenti](04-modules-and-tools.md)**
