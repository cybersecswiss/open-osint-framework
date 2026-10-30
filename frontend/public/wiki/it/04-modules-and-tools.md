# Moduli e strumenti

Una **ricerca** esegue uno o più **moduli**. Ogni modulo raggruppa diversi
**strumenti** che interrogano vere fonti OSINT. Non richiama mai gli
strumenti direttamente — sceglie un **tipo di query**, digita un indicatore
e spunta i moduli desiderati. Il sistema esegue automaticamente ogni
strumento che comprende quel tipo di query.

Esistono **14 moduli** (circa 85 strumenti, tre dei quali disattivati di default). Alcuni strumenti richiedono una
chiave API configurata dal suo gestore; senza di essa, solo quello
strumento restituisce una chiara nota "chiave non impostata" invece di far
fallire la ricerca. Alcuni moduli sono opt-in e compaiono solo se la sua
autorità dispone della relativa licenza.

| # | Modulo | A che cosa serve | Chiave necessaria? |
|---|--------|---------------|--------------|
| 1 | **Pivot di alias** (`alias`) | Trovare un nome utente/alias sul web | No |
| 2 | **Leak e violazioni** (`leaks`) | E-mail/nome utente in violazioni di dati + impronta degli account | In parte |
| 3 | **Infrastruttura** (`infra`) | Ricognizione di domini / IP, sosia di phishing | In parte |
| 4 | **Threat intel** (`threat`) | Reputazione e attribuzione malware di un IOC | In parte |
| 5 | **Darknet e paste** (`darknet`) | Servizi nascosti Tor, paste, **sorveglianza dei sequestri** | No |
| 6 | **Messaggistica** (`messenger`) | Anteprima Telegram senza chiave, Discord, telefono→messenger | In parte |
| 7 | **Tracciamento crypto** (`crypto`) | Indirizzi Bitcoin / Ethereum + attribuzione dei wallet | In parte |
| 8 | **Telegram (approfondito)** (`telegram`) | Raccolta Telegram autenticata e approfondita | Sessione |
| 9 | **Compliance** (`compliance`) | Verifica di sanzioni / PEP / liste di controllo | In parte |
| 10 | **Forum criminali** (`forums`) | Ricerca nei forum, indice dei threat actor, PGP, directory di link | In parte |
| 11 | **OSINT Immagini** (`image`) | EXIF/GPS delle foto + stima IA del luogo | In parte |
| 12 | **Notizie & RSS** (`news`) | Ricerca a testo integrale nei feed di autorità, polizia, media e cyber | No |
| 13 | **Aziende & persone** (`corporate`) | Registri, struttura di gruppo, liste di sanzioni, elenchi — vedi [la pagina dedicata](15-companies-and-people.md) | No |
| 14 | **Dating & adulti** (`dating`) | Ricerca di nomi utente su siti dating/per adulti — **disattivato di default** | No |

---

## 1. Pivot di alias — `alias`

Trasforma un nome utente o un alias in una mappa di account.

| Strumento | Fonte | Note |
|------|--------|-------|
| `sherlock` | 600+ piattaforme | Verifica dove esiste un nome utente |
| `whatsmyname` | Elenco di siti aggiornato in tempo reale | Copertura delle piattaforme sempre attuale |
| `user_scanner` | Multi-sito | Ampia scansione della presenza di un nome utente |
| `linkook` | Grafo degli account collegati | Segue i collegamenti tra i profili di un utente |

**Tipo di query:** `Nome utente / Alias`. Ogni risultato viene nuovamente
verificato per eliminare i falsi positivi, per cui un account elencato
esiste davvero.

## 2. Leak e violazioni — `leaks`

Dove un'e-mail/un nome utente è emerso in violazioni di dati e presso quali
servizi è registrato.

| Strumento | Fonte | Chiave |
|------|--------|-----|
| `holehe` | ~120 siti | No — l'indirizzo vi è registrato? |
| `hibp` | HaveIBeenPwned | Sì (`HIBP_API_KEY`) |
| `intelx` | Intelligence X | No — produce un link diretto |
| `ghunt` | Account Google | Sessione — e-mail/Gaia-ID → profilo Google dettagliato, recensioni Maps |
| `hudsonrock` | Intelligence sugli infostealer | Senza chiave — e-mail/dominio → infezioni da infostealer |

**Tipi di query:** `E-mail` (+ `hudsonrock` anche nome utente/dominio,
`ghunt` anche un Gaia ID).

> Le **password** vengono salvate solo come impronta SHA-256 + anteprima
> mascherata (`a••••z`), a meno che il suo gestore non abiliti
> esplicitamente il testo in chiaro.

## 3. Infrastruttura — `infra`

Ricognizione di domini e IP — e individuazione dell'infrastruttura di
**phishing/sosia** attorno a un marchio.

| Strumento | Fonte | Chiave |
|------|--------|-----|
| `subfinder` | Enumerazione dei sottodomini | No |
| `whois` | Registrazione / titolarità | No |
| `crtsh` | Log di Certificate Transparency | No |
| `dns_records` | A / AAAA / MX / NS / TXT / CNAME | No |
| `theharvester` | E-mail/host di un dominio | No |
| `shodan_host` | Porte aperte, banner, CVE | Sì (`SHODAN_API_KEY`) |
| `favicon_pivot` | Stessa favicon → host correlati | Sì (Shodan) |
| `dnstwist` | **Domini typosquat / phishing** | No |
| `passive_dns` | Risoluzioni dominio↔IP **storiche** (Mnemonic) | No |
| `asn_lookup` | Chi instrada questo indirizzo: prefisso, AS, titolare (RIPEstat) | No |
| `origin_resolve` | Server reale dietro una CDN (Cloudflare & co.), confermato con interrogazione diretta — **disattivato di default** (`ENABLE_ORIGIN_RESOLVE`) | No |

**Tipi di query:** `Dominio`, `Indirizzo IP`, `URL`.
`dnstwist` trasforma un dominio nell'elenco dei domini sosia registrati
(omoglifi/IDN, bitsquatting, cambio di TLD …) che risolvono effettivamente —
candidati attivi di phishing/usurpazione d'identità su cui fare pivot.

**`passive_dns` è quello che guarda all'indietro.** Tutti gli altri
strumenti qui rispondono a "che cosa è vero adesso" — che è esattamente lo
stato che un operatore modifica non appena si sa scoperto. Il DNS passivo
risponde a "a che cosa puntava questo dominio lo scorso marzo", in entrambe
le direzioni, ed è lì che di solito si trova il pivot. `asn_lookup` aggiunge
un nuovo nodo `asn`, così che gli host instradati dalla stessa rete
convergano nel grafo — lo schema tipico del bulletproof hoster.

## 4. Threat intel — `threat`

Reputazione, classificazione e **attribuzione malware** di un indicatore.

| Strumento | Fonte | Chiave |
|------|--------|-----|
| `virustotal` | VirusTotal | Sì |
| `abuseipdb` | AbuseIPDB | Sì |
| `urlhaus` | abuse.ch URLhaus | Senza chiave/Chiave |
| `greynoise` | GreyNoise community | Senza chiave |
| `urlscan` | urlscan.io | Senza chiave |
| `threatfox` | abuse.ch ThreatFox (IOC→malware) | Chiave |
| `malwarebazaar` | abuse.ch MalwareBazaar (hash→campione) | Chiave |
| `ransomware_watch` | Vittime dei siti di leak, gruppi, i loro siti onion | Facoltativa |
| `c2_intel` | Infrastruttura di **comando e controllo** nota, da scansioni Censys | No |
| `ioc_reputation` | **Quante blocklist indipendenti** riportano questo indicatore | No |
| `cve_lookup` | Dettagli CVE **più** lo stato di sfruttamento attivo (NVD + CISA KEV) | No |

**Tipi di query:** `Dominio`, `Indirizzo IP`, `URL`, `Hash`, `ID CVE`,
`Parola chiave`.

Tre di questi vanno compresi come gruppo, perché rispondono a domande
diverse sullo stesso indirizzo:

* `c2_intel` — *questo host è stato visto servire un pannello C2, e per
  quale famiglia di malware?* Un risultato è un'osservazione del software
  stesso, non un'opinione.
* `ioc_reputation` — *quante blocklist indipendenti lo elencano?* Una sola
  lista dice poco; la concordanza tra liste che non condividono una fonte
  dice molto. La risposta indica quante liste sono state consultate, così
  un numero basso si legge come copertura e non come innocenza.
* `cve_lookup` — *questa vulnerabilità viene effettivamente sfruttata?* Se
  il catalogo CISA non è raggiungibile, "sfruttata" viene riportato come
  **sconosciuto**, mai come "no".

`ransomware_watch` funziona senza chiave, ma è allora limitato a una
richiesta al minuto per endpoint; una chiave gratuita di my.ransomware.live
elimina questo limite e lo strumento la rileva da sé.

## 5. Darknet e paste — `darknet`

| Strumento | Tipo di query | Che cosa fa |
|------|-----------|--------------|
| `ahmia` | `Parola chiave` | Ricerca in tempo reale di servizi nascosti Tor (Torch/TorDex) |
| `paste_search` | `Parola chiave` | Indice dei siti paste |
| `seizure_watch` | `Dominio` (o `.onion`) | **FBI-Watchdog:** rileva un **sequestro/takedown** da parte delle forze dell'ordine (banner di sequestro, nomi delle autorità) e fotografa l'infrastruttura (record A/NS, reindirizzamento) per poter individuare in seguito un cambiamento |
| `onion_scrape` | `Indirizzo onion` | Scarica un servizio nascosto tramite Tor ed estrae contatti/IOC — **disattivato di default** (`ENABLE_ONION_SCRAPE`) |

## 6. Messaggistica — `messenger`

Telegram + Discord senza chiave, più telefono→messenger.

| Strumento | Tipo di query | Che cosa fa |
|------|-----------|--------------|
| `telegram_channel` | `Canale Telegram` | Anteprima pubblica del canale |
| `tgstat` | `Canale Telegram` | Statistiche/analisi del canale |
| `telegram_username_hunt` | `Nome utente` | Scansiona canali criminali noti alla ricerca dell'alias |
| `telegram_search` / `telegram_global_search` | `Ricerca canali Telegram` | Motori di ricerca Telegram pubblici |
| `telegram_message_search` | `Ricerca messaggi Telegram` | Parola chiave nell'anteprima pubblica |
| `discord_invite` | `Invito Discord` | Risolve un invito → informazioni sul server |
| `discord_snowflake` | `ID Discord` | Decodifica un ID utente → **data di creazione dell'account** (senza chiave) |
| `discord_deep` | `ID Discord` | **Profilo pubblico completo** (nome, avatar/banner, badge) — richiede `DISCORD_BOT_TOKEN` |
| `phone_messenger` | `Numero di telefono` | Normalizza un numero (paese/operatore/tipo di linea) + un **link diretto WhatsApp** da verificare manualmente |

> `phone_messenger` non afferma mai che un numero "è su WhatsApp" — non
> esiste una verifica automatizzata conforme. Le fornisce i dati verificati
> del numero e un link che apre lei stesso.

## 7. Tracciamento crypto — `crypto`

| Strumento | Fonte | Chiave |
|------|--------|-----|
| `blockchain_btc` | blockchain.info | Senza chiave |
| `etherscan_eth` | Etherscan | Sì (`ETHERSCAN_API_KEY`) |
| `blockscout` | Blockscout (alternativa ETH senza chiave) | Senza chiave |
| `wallet_attribution` | MistTrack | Sì — wallet → cluster exchange/mixer/truffa/ransomware + rischio |

**Tipi di query:** `Indirizzo Bitcoin`, `Indirizzo Ethereum`.

## 8. Telegram (approfondito) — `telegram`

Raccolta MTProto autenticata — cronologia completa, membri e ricerche di
utenti/telefoni/posizioni. Richiede una **sessione** Telegram configurata
dal suo gestore. Pagina dedicata: **[Strumenti Telegram](05-telegram.md)**.

## 9. Compliance — `compliance`

| Strumento | Fonte | Chiave |
|------|--------|-----|
| `opensanctions` | OpenSanctions (OFAC/UE/ONU/SECO…) | Sì, oppure self-hosting senza chiave |

Verifica un **nome, un'azienda o un wallet crypto** rispetto a liste di
sanzioni / PEP / liste di controllo. **Tipi di query:** `Parola chiave`/nome,
indirizzo crypto.

## 10. Forum criminali — `forums`

| Strumento | Che cosa fa | Chiave |
|------|--------------|-----|
| `crime_forum_hunt` | Esegue dork su forum criminali clearnet + darknet per un termine/alias/ID di contatto | La chiave Brave aiuta |
| `threat_actor_check` | Cerca un alias in un ampio indice di threat actor | Senza chiave |
| `linkbase_lookup` | Consultazione di directory curate di link darknet | Senza chiave |
| `pgp_lookup` | Trova/analizza la chiave PGP di un attore + l'impronta | Senza chiave |

**Tipi di query:** `Parola chiave`, `Nome utente`, più ID di contatto
(`Jabber`, `Tox`, `Session`, impronta PGP).

## 11. OSINT Immagini — `image`

Estrarre indizi di luogo da una foto. **Tipo di query:** `URL immagine`.

| Strumento | Che cosa fa | Chiave |
|------|--------------|-----|
| `exif_gps` | Legge i dati EXIF incorporati: marca/modello della fotocamera, data e ora, e **GPS** → un nodo `location` con il nome del luogo | No |
| `visual_geolocate` | In assenza di GPS, un'**IA stima il luogo** in base a indizi visibili (cartelli, architettura) — chiaramente contrassegnato come *stima IA*, una pista da verificare | Sì (Gemini) |

> La stima dell'IA è una pista, non una prova. Se il modello non è in
> grado di stabilirlo, lo dice e non aggiunge nulla — non inventa mai un
> luogo.

## 12. Notizie & RSS — `news`

| Strumento | Tipo di query | Che cosa fa |
|------|-----------|--------------|
| `news_search` | `Parola chiave` | Ricerca a testo integrale nei feed gestiti dal suo gestore — enti federali, polizia, media, tecnologia e cyber |

Ogni risultato riporta **data, fonte e tipo di fonte**. Un comunicato di
un'autorità e un articolo di giornale sono entrambe piste legittime, ma non
hanno lo stesso peso probatorio; per questo alle fonti ufficiali è anche
attribuita una confidenza più elevata. Vedi
[Eseguire una ricerca](03-searching.md#news--rss).

---

Avanti: **[Strumenti Telegram →](05-telegram.md)** · Indietro: **[Ricerca](03-searching.md)**

## 14. Dating & adulti — `dating`

**Disattivato di default.** L'operatore lo attiva deliberatamente con
`ENABLE_DATING_SEARCH=true`; fino ad allora il modulo non offre alcuno strumento.
Pensato per piste concrete come sextortion, truffe sentimentali o tratta.

> ⚠️ Avere un profilo su una piattaforma dating o per adulti è
> un'informazione sulla vita sessuale di una persona — dati particolarmente
> degni di protezione. Cercare solo con una base legale e uno scopo precisi e
> trattare questi casi in modo riservato.

| Strumento | Tipo di query | Cosa fa |
|-----------|---------------|---------|
| `cupidcrawl` | `Nome utente` | Scansiona ~50 piattaforme dating/per adulti; ogni risultato è verificato con un controllo negativo |

