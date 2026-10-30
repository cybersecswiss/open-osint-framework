# Monitoraggio & avvisi

Un monitoraggio **ripete la ricerca di un'entità a intervalli fissi** e
segnala con un avviso ciò che si è aggiunto dall'ultima esecuzione.

## Creare un monitoraggio

**Consigliato:** nel caso, apra l'entità (scheda del nodo o clic destro nel
grafico) → **«Attiva monitoraggio»**. La finestra è precompilata con
l'entità. **In alternativa:** **Monitoraggio** → **«Nuovo monitoraggio»**, poi
scegliere caso ed entità.

Nella finestra:

- **Scopo / base legale** — perché questo termine è monitorato; obbligatorio
  se la Sua autorità lo richiede (vedi [Eseguire una ricerca](03-searching.md)).
- **Intervallo** — *Ogni ora*, *Giornaliero* (predefinito), *Settimanale* o
  *Mensile*.
- **«Avvisa su»** — *Nuovo risultato nel caso*, *Nuovo account,
  profilo o identificativo*, *Nuovo collegamento dell'entità monitorata*.
  Nessuna selezione = tutti i cambiamenti.
- **E-mail / webhook di avviso** — facoltativo per monitoraggio; il canale per
  l'intera autorità è configurato dall'amministrazione in **Admin → Avvisi**.

La **prima esecuzione è volutamente silenziosa**: registra ciò che esiste già,
così viene segnalato solo ciò che compare dopo.

## Avvisi

I nuovi avvisi compaiono nella **Dashboard** («Avvisi non letti») e nella
pagina **Avvisi** per tutti i casi: prima i non letti, selezione multipla per
segnarli come letti, **«Apri il caso»** porta direttamente al risultato. Se la
Sua amministrazione ha configurato e-mail o webhook, gli avvisi vengono
inviati anche lì.

Vengono proposti solo i cambiamenti che la piattaforma può davvero rilevare.
Non conserva stati precedenti dei profili e non può distinguere un profilo
cancellato da un'interrogazione non riuscita — «profilo modificato» o
«account cancellato» non sono quindi attivatori. I monitoraggi più vecchi che
li usavano mostrano un'indicazione e continuano con gli altri.

## Gestire i monitoraggi

L'elenco **Monitoraggio** mostra per ciascuno entità, intervallo, stato e
prossima esecuzione. **«Configura»** lo apre: impostare **Attivo / Inattivo**,
modificare intervallo, attivatori e invio, poi **«Salva»**. Le ricerche
automatiche figurano nel **«Registro delle ricerche»** del caso.

---

Avanti: **[Rapporti →](08-reports.md)** · Indietro: **[Leggere il grafico](06-reading-the-graph.md)**
