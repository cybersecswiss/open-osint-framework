# Varianti di scrittura

Le indagini sulla cibercriminalità raramente cominciano con il nome di una
persona. Cominciano con un **handle** — e gli handle non vengono mai scritti
due volte allo stesso modo. Lo stesso attore è `d4rkc1ph3r` su un forum,
`darkcipher` sul successivo, `dark_cipher` su un terzo e `darkcipher1` dopo
un ban.

Una ricerca della sola stringa esatta digitata perde il risultato già per un
solo carattere sostituito, e nulla lo segnala. Per questo la piattaforma
cerca anche le varianti ortografiche.

## Che cosa viene ora cercato insieme al suo input

| Schema | Esempio |
|---|---|
| Leetspeak | `d4rkc1ph3r` ↔ `darkcipher` |
| Separatori | `dark_cipher`, `dark.cipher`, `dark-cipher` |
| Numeri finali | `darkcipher1` → `darkcipher` |
| Cirillico → latino | `Пётр` → `petr` |

Funzionano in **entrambe le direzioni**: cercare `darkcipher` trova anche
`d4rkc1ph3r`, e viceversa.

## La regola che conta: un candidato non è un'identità

Un risultato ottenuto tramite una variante significa:

> Esiste un account la cui grafia corrisponde alla sua ricerca.

**Non** significa:

> Si tratta della stessa persona.

`darkcipher` su Reddit e `d4rkc1ph3r` su XSS possono essere due persone a cui
piace la stessa parola. La piattaforma le tiene quindi visibilmente
separate:

* i risultati da varianti recano **`match_type: variant`** e indicano la
  grafia che li ha prodotti
* sono **valutati più in basso** di un risultato diretto
* la loro relazione nel grafo è `possible_handle_variant` o
  `possible_account_of` — mai `is_account_of`
* una nota sopra l'elenco dei risultati indica quanti risultati provengono
  da varianti

**Ciò che trasforma un candidato in un risultato è un secondo segnale:** la
stessa password, la stessa chiave PGP, lo stesso forum, lo stesso wallet, le
stesse abitudini di scrittura. È a questo che serve la corroborazione (vedi
*Valutare i risultati*). Registri il ragionamento nel campo nota del nodo —
compare accanto al risultato nel rapporto.

## Dove si applica

**Automaticamente, senza costi**

*Attori noti* (`threat_actor_check`) confronta il suo handle e le sue
varianti con un indice di 830 000 nomi utente provenienti da 25 forum
criminali. L'indice è locale, per cui la ricerca delle varianti non costa
nulla e richiede millisecondi.

**Su richiesta, perché richiede tempo**

*Scansione handle (varianti di scrittura)* nel modulo **Alias** sonda circa
600 piattaforme — una volta per ogni grafia. Un'esecuzione richiede quindi
da uno a tre minuti invece di cinquanta secondi. Scelga lo strumento
deliberatamente quando un handle è al centro di un caso.

Il guadagno è reale: nei test, `d4rkc1ph3r` da solo ha restituito 8
account; con le varianti ne ha restituiti 54.

## Limiti da conoscere

**I separatori possono essere rimossi, ma non inventati.** `tony-stark`
trova `tonystark`. Il contrario non funziona — non c'è modo di sapere che la
separazione va dopo `tony` anziché dopo `to`. **Nel dubbio, cerchi la grafia
più separata**; trova di più.

**Gli handle brevi non ricevono varianti.** Al di sotto dei quattro
caratteri ogni risultato sarebbe rumore: `b0b` per `bob` è quasi certamente
un'altra persona.

**Il numero di grafie è limitato.** La scansione degli handle ne sonda al
massimo quattro. È deliberato — un elenco di varianti illimitato produce
candidati a cui nessun inquirente avrebbe pensato, ed è esattamente da lì
che nascono le false piste.

## Nomi di persone

I nomi di persona seguono meccanismi diversi da quelli degli handle: la
verifica delle sanzioni confronta **parole intere, in
qualsiasi ordine**. "Vladimir Putin" e "Putin Vladimir" restituiscono ora lo
stesso risultato — in precedenza una delle due liste ufficiali veniva
esclusa a seconda di come si digitava il nome, perché l'UE scrive "Vladimir
PUTIN" e gli Stati Uniti scrivono "PUTIN, Vladimir". La verifica resta
esplicitamente non approssimativa: vengono confrontate solo **parole
intere**, così nessuno finisce per errore su una lista di sanzioni.
