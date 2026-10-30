# Surveillance & alertes

Une surveillance **répète la recherche d'une entité à intervalle fixe** et
signale par une alerte ce qui s'est ajouté depuis la dernière exécution.

## Créer une surveillance

**Recommandé :** dans le dossier, ouvrez l'entité (fiche du nœud ou clic droit
dans le graphe) → **« Activer la surveillance »**. La boîte de dialogue est
préremplie avec l'entité. **Autre possibilité :** **Surveillance** →
**« Nouvelle surveillance »**, puis choisir le dossier et l'entité.

Dans la boîte de dialogue :

- **Finalité / base légale** — pourquoi ce terme est surveillé ; obligatoire
  si votre autorité l'exige (voir [Lancer une recherche](03-searching.md)).
- **Intervalle** — *Toutes les heures*, *Quotidien* (par défaut),
  *Hebdomadaire* ou *Mensuel*.
- **« Alerter sur »** — *Nouveau résultat dans le dossier*, *Nouveau
  compte, profil ou identifiant*, *Nouveau lien de l'entité surveillée*. Aucune
  sélection = tous les changements.
- **E-mail / webhook d'alerte** — facultatif par surveillance ; le canal de
  toute l'autorité est configuré par l'administration sous **Admin → Alertes**.

La **première exécution est volontairement silencieuse** : elle consigne ce
qui existe déjà, afin que seul ce qui apparaît ensuite soit signalé.

## Alertes

Les nouvelles alertes apparaissent sur le **Tableau de bord** (« Alertes non lues ») et sur la page **Alertes** pour tous les dossiers : non lues d'abord,
sélection multiple pour les marquer comme lues, **« Ouvrir le dossier »** mène
directement au résultat. Si votre administration a configuré un e-mail ou un
webhook, les alertes y sont aussi envoyées.

Seuls les changements que la plateforme peut réellement détecter sont
proposés. Elle ne conserve pas d'états antérieurs des profils et ne peut pas
distinguer un profil supprimé d'une requête échouée — « profil modifié » ou
« compte supprimé » ne sont donc pas des déclencheurs. Les anciennes
surveillances qui les utilisaient affichent une remarque et continuent avec
les autres.

## Gérer les surveillances

La liste **Surveillance** montre pour chacune l'entité, l'intervalle, le
statut et la prochaine exécution. **« Configurer »** l'ouvre : passer
**Active / Inactive**, modifier intervalle, déclencheurs et envoi, puis
**« Enregistrer »**. Les recherches automatiques figurent dans le **« Journal
des recherches »** du dossier.

---

Suite : **[Rapports →](08-reports.md)** · Retour : **[Lire le graphe](06-reading-the-graph.md)**
