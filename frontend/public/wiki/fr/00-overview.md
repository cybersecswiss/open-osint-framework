# Plateforme OSINT — Manuel d'utilisation

Bienvenue. Ce manuel explique comment mener des enquêtes sur la plateforme
OSINT : se connecter, créer un dossier, rechercher dans les sources de
données, lire le graphe des relations, surveiller des cibles dans le temps
et exporter des rapports.

Il s'adresse aux **enquêteurs et enquêtrices** (utilisateurs finaux).
L'installation, les serveurs et les identifiants sont traités séparément
dans le manuel d'exploitation (`docs/operations.en.md`).

## Sommaire

1. **[Premiers pas](01-getting-started.md)** — se connecter avec son
   adresse e-mail professionnelle et s'orienter dans l'application.
2. **[Travailler avec les dossiers](02-cases.md)** — chaque enquête vit
   dans un dossier ; comment les créer et les gérer.
3. **[Lancer une recherche](03-searching.md)** — le déroulement central :
   choisir un type de requête, saisir un indicateur, choisir les modules,
   suivre la progression.
4. **[Modules & outils](04-modules-and-tools.md)** — les modules de
   collecte et chacun des outils qu'ils contiennent.
5. **[Outils Telegram (approfondi)](05-telegram.md)** — collecte Telegram
   authentifiée : analyses de canaux, recherches par utilisateur /
   téléphone / géolocalisation.
6. **[Lire le graphe](06-reading-the-graph.md)** — comment explorer les
   entités et les relations produites par une recherche.
7. **[Évaluer les résultats](12-assessing-findings.md)** — cotations,
   confirmation croisée, pertinence et preuves : décider lesquels de
   plusieurs centaines de résultats comptent vraiment.
8. **[Suivre les changements](13-tracking-changes.md)** — ce qu'une
   nouvelle exécution a ajouté, et ce que la plateforme ne peut
   délibérément pas vous dire.
9. **[La fonction IA](11-ai-function.md)** — mise en relation assistée,
   là où elle est sous licence.
10. **[Surveillance & alertes](07-monitoring-and-alerts.md)** — surveiller
    une cible et être averti lorsque quelque chose change.
11. **[Rapports](08-reports.md)** — transformer un dossier en rapport
    transmissible.
12. **[Exporter un dossier](14-exporting.md)** — CSV, Maltego, MISP et
    STIX pour remettre des résultats à un autre système ou à une autre
    autorité.
13. **[Référence & glossaire](09-reference.md)** — types de requête, types
    d'entités, relations des arêtes et dépannage.
14. **[Support & tickets](10-support.md)** — joindre l'exploitant.

## En une minute

1. Ouvrez l'URL de la plateforme et connectez-vous avec votre **adresse
   e-mail professionnelle**.
2. Créez un **dossier** pour votre enquête.
3. Ouvrez le dossier et lancez une **recherche** : choisissez un *type de
   requête* (nom d'utilisateur, e-mail, domaine, IP, téléphone, canal
   Telegram, adresse crypto, …), saisissez l'indicateur, cochez les
   **modules** à exécuter et démarrez.
4. Les résultats apparaissent dans le dossier sous forme de **graphe**
   d'entités et de relations. Cliquez sur un nœud pour voir les détails ;
   double-cliquez pour approfondir (pivot).
5. Si vous le souhaitez, mettez une cible sous **surveillance** ou exportez
   un **rapport**.

> **Vos données restent les vôtres.** Les données d'enquête (dossiers,
> entités, résultats) sont stockées dans le système de votre propre
> organisation. L'exploitant de la plateforme fait fonctionner le logiciel,
> mais ne peut pas lire les données de vos dossiers.

---

Commencez ici : **[Premiers pas →](01-getting-started.md)**
