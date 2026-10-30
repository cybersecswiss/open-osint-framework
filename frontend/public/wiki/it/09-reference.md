# Riferimento e glossario

## Tipi di query

Il **tipo di query** indica alla piattaforma come interpretare il suo
termine di ricerca e quali moduli/strumenti possono trattarlo. Lo scelga
dal menu a tendina *Tipo* nel modulo di ricerca.

| Tipo di query (menu a tendina) | Esempio di input | Trattato di solito da |
|-----------------------|---------------|----------------------|
| Nome utente / Alias | `anonymous99` | alias, leaks (hudsonrock), messenger (ricerca del nome utente) |
| E-mail | `max@example.com` | leaks |
| Dominio | `example.com` | infra, threat |
| Indirizzo IP | `1.2.3.4` | infra, threat |
| URL | `http://bad.example/x` | threat |
| Hash (MD5/SHA1/SHA256) | `sha256:…` | threat |
| Numero di telefono | `+41790000000` | **telegram** |
| Indirizzo Bitcoin | `bc1q…` | crypto |
| Indirizzo Ethereum | `0x…` | crypto |
| Canale Telegram | `@durov` | messenger (senza chiave), **telegram** (approfondito) |
| Ricerca canali Telegram | `ransomware` | messenger |
| Ricerca messaggi Telegram | `@chan :: keyword` | messenger |
| Utente Telegram / ID | `@user` | **telegram** |
| Geo Telegram (lat,long) | `47.3769,8.5417` | **telegram** |
| Invito Discord | `discord.gg/abc` | messenger |
| Parola chiave (forum/darknet/paste) | `acme breach` | darknet |

Nel modulo di ricerca compaiono come opzioni selezionabili solo i moduli
che comprendono il tipo di query scelto.

## Tipi di entità nel grafo

I nodi sono colorati secondo il tipo. I tipi sconosciuti appaiono in grigio
e funzionano comunque.

| Colore | Tipo di entità | Significato |
|:------:|-------------|---------|
| 🔵 | `person` | Una persona |
| 🟢 | `social_account` | Un account di social media |
| 🟠 | `organization` | Un'organizzazione |
| 🔴 | `email_address` | Un indirizzo e-mail |
| 🟣 | `domain` | Un dominio |
| 🩵 | `username` | Un nome utente / alias |
| 🩷 | `ip_address` | Un indirizzo IP |
| 🟢 | `phone_number` | Un numero di telefono |
| 🟧 | `location` | Un luogo geografico |
| 🔵 | `telegram_channel` | Un canale/gruppo Telegram |
| 🔵 | `telegram_message` | Un messaggio Telegram |
| 🔵 | `telegram_user` | Un utente Telegram |
| 🔵 | `telegram_media` | Un file multimediale in Telegram |
| 🔴 | `telegram_ioc` | Un indicatore (crypto/e-mail/URL/…) trovato in un messaggio |
| 🟣 | `telegram_linked_channel` | Un canale citato tramite un inoltro |

## Relazioni tra archi

Gli archi sono etichettati con la relazione. La raccolta Telegram produce:

`POSTED` · `POSTED_IN` · `IN_CHANNEL` · `MEMBER_OF` · `ADMIN_OF` ·
`PINNED_IN` · `REPLY_TO` · `FORWARDED_FROM` · `MENTIONS` · `HAS_MEDIA` ·
`COMMON_CHAT` · `LINKED_DISCUSSION` · `SIMILAR_TO`

Gli altri moduli aggiungono le proprie (p. es. un collegamento da alias ad
account). Passi con il mouse su un arco nel grafo per vederne l'etichetta.

## Tipi di indicatori (IOC) estratti dal testo Telegram

`btc` · `eth` · `xmr` · `ltc` · `tron` (indirizzi crypto) · `email` ·
`url` · `telegram_link` · `phone` · `mention` (@handle) · `hashtag`.

## Glossario

- **Caso** — il contenitore di un'indagine. Ogni risultato di ricerca è
  collegato a un caso.
- **Entità** — un nodo nel grafo del caso (una persona, un account, un
  canale, un indirizzo, un messaggio, …).
- **Arco** — una relazione etichettata tra due entità.
- **Modulo** — un collettore autonomo (uno degli 8). Sceglie lei quali
  eseguire per ogni ricerca.
- **Strumento** — una singola fonte all'interno di un modulo (p. es.
  `virustotal`).
- **Tipo di query** — come viene interpretato il suo termine di ricerca
  (vedi sopra).
- **IOC** — Indicator of Compromise (indicatore di compromissione): un
  indirizzo crypto, un'e-mail, un URL, un hash, ecc.
- **Tenant** — la sua organizzazione. I suoi dati risiedono nell'archivio
  della sua organizzazione; il gestore della piattaforma non può leggerli.
- **Sessione (Telegram)** — il login Telegram autenticato usato dal modulo
  approfondito; gestito dal suo gestore.

## Risoluzione dei problemi

| Sintomo | Significato / che cosa fare |
|---------|----------------------|
| Una riga di strumento mostra la nota "chiave non impostata" | Quella fonte richiede una chiave API che il suo gestore non ha configurato. Gli altri strumenti sono stati eseguiti comunque. |
| Gli strumenti Telegram indicano "not authenticated" | La sessione Telegram è inattiva — chieda al suo gestore di autenticarla nuovamente. |
| Non compare alcun modulo per il mio tipo di query | Nessun modulo installato tratta quel tipo; scelga un altro tipo o un altro termine. |
| Un nodo sembra scollegato | È il termine che ha cercato (la "radice"), oppure un'estremità per la quale nessuno strumento ha restituito dettagli completi. |
| Ricerca conclusa ma pochi risultati | Normale — un esito negativo pulito (come un'e-mail senza violazioni di dati) è un risultato valido. |

## Impostazioni dell'autorità (per gli amministratori)

In **Admin → Impostazioni** l'amministrazione della Sua autorità stabilisce per
tutti:

| Impostazione | Effetto |
|---|---|
| Nome visualizzato, logo | Intestazione e copertina dei rapporti |
| Lingua predefinita | Lingua dell'interfaccia finché un utente non ne sceglie una |
| Richiedere uno scopo per ogni ricerca | Ricerche e nuovi monitoraggi richiedono uno scopo / base legale, registrato nel registro delle ricerche |
| Menzione di classificazione nel rapporto | In rosso su ogni pagina di ogni rapporto PDF |
| Playbook predefinito | Preselezionato nella ricerca quando è adatto |
| Moduli disattivati | Moduli con licenza che la Sua autorità non usa — tolti dalla ricerca e dai monitoraggi esistenti |
| Timeout di sessione, cancellazione automatica | Disconnessione dopo inattività; cancellazione dei casi chiusi dopo N mesi |

Qui i moduli possono solo essere **disattivati**; quali moduli sono in licenza
fa parte del Suo contratto con il gestore della piattaforma.

**Autotest.** *Admin → Autotest* verifica, in un elenco con semaforo, se la
Sua installazione funziona: licenza, archivio (raggiungibile, chiave accettata,
aggiornato), certificato TLS, integrità della catena del registro, servizio di
accesso, canale di avviso e salvataggio prove — ciascuno con una frase su cosa
fare. Da eseguire dopo ogni installazione o aggiornamento.

---

Indietro: **[Pagina iniziale](00-overview.md)**
