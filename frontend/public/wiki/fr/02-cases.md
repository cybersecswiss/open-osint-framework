# Travailler avec les dossiers

Chaque enquête vit dans un **dossier**. Tous les résultats de recherche sont
rattachés à un dossier ; la première étape consiste donc toujours à en avoir
un d'ouvert.

## Créer un dossier

1. Allez dans **Dossiers** et cliquez sur **« Nouveau dossier »** (en haut à
   droite).
2. Remplissez :
   - **« Titre »** (obligatoire) — un nom court pour l'enquête.
   - **« Priorité »** — *Normale*, *Élevée* ou *Urgente* (par défaut
     *Normale*).
3. Confirmez. Le dossier reçoit automatiquement un **numéro de dossier**.

> Vous pouvez aussi créer un dossier à la volée depuis le formulaire de
> recherche, avec le bouton **« Nouveau »** à côté de *« Attribuer au
> dossier »*.

La boîte de dialogue de création ne contient pas de **description** —
ajoutez-la plus tard via **« Modifier »** à l'intérieur du dossier.

## La liste des dossiers

Le tableau **Dossiers** affiche **« Numéro de dossier »**, **« Titre »**,
**« Statut »**, **« Priorité »** et **« Créé »**. Cliquez sur une ligne pour
l'ouvrir.

Un **clic droit** sur une ligne propose des actions rapides : *« Ouvrir le
dossier »*, *« Copier le numéro du dossier »*, *« Copier l'ID »* et (admins
uniquement) *« Supprimer »*.

## À l'intérieur d'un dossier

L'en-tête du dossier affiche le numéro de dossier, le titre et les
étiquettes de statut et de priorité, ainsi que des boutons :

- **« Rapport PDF »** — un rapport écrit sur le dossier (voir
  [Rapports](08-reports.md)).
- **« Exporter »** — le même dossier au format CSV, Maltego, MISP ou STIX
  ([Exporter](14-exporting.md)).
- **« Modifier »** — changer le titre, la **description**, le statut
  (*Ouvert / En cours / Fermé / Archivé*), la priorité ou **« Attribué
  à »**.
- **« Supprimer »** — admins uniquement.

Sous l'en-tête se trouvent les onglets du dossier :

1. **« Résultats »** — les résultats sous forme de liste de travail, triés
   par pertinence ([comment les résultats sont évalués](12-assessing-findings.md)).
   C'est l'onglet par lequel commencer.
2. **« Graphe réseau »** — la carte visuelle de tout ce qui a été trouvé
   ([comment le lire](06-reading-the-graph.md)).
3. **« Carte (N) »** — tous les résultats porteurs de coordonnées, placés
   géographiquement, avec une chronologie à côté. Utile seulement lorsqu'un
   dossier contient des résultats localisés (lieux, avis, images
   géolocalisées).
4. **« Liste (N) »** — les mêmes entités sous forme de tableau consultable
   et triable.
5. **« Nouveau depuis la dernière exécution »** — ce que la recherche la
   plus récente a ajouté ([suivre les changements](13-tracking-changes.md)).
6. **« Nouvelle recherche »** — lancer une recherche dont les résultats
   arrivent directement dans ce dossier ([fonctionnement de la
   recherche](03-searching.md)).

## Faire le tri dans les résultats

Au fur et à mesure que les résultats arrivent, vous voudrez séparer le
signal du bruit :

- **Marquer comme pertinent** — signale une entité clé (étoile dorée + halo
  dans le graphe) pour qu'elle ressorte et apparaisse en bonne place dans
  les rapports.
- **« Retirer comme faux positif »** — supprime du dossier une entité et ses
  liens lorsqu'il s'agit manifestement de bruit.

Les deux actions sont disponibles par clic droit sur un nœud, depuis le
panneau de détails du nœud ou depuis la colonne *Actions* de l'onglet
**Liste**.

## Journal des recherches

L'onglet **« Journal des recherches »** liste chaque recherche du dossier :
quand, par qui, avec quel terme et quelle **finalité / base légale**. Les
recherches automatiques d'une surveillance apparaissent comme *« Recherche
automatique »*. Le journal se trouve dans le stockage de données de votre
autorité ; l'exploitant de la plateforme ne peut pas le lire.

## Modèles de dossier

Lors de la création d'un dossier, vous pouvez choisir un **modèle (type
d'infraction)** — rançongiciel, hameçonnage, commerce darknet, sextorsion,
etc. C'est un point de départ, pas une règle :

- la **recherche** du dossier présélectionne le playbook adapté (modules),
- le **rapport** démarre avec une structure adaptée au type d'infraction,
- une étiquette bleue dans l'en-tête du dossier indique le modèle ; au survol,
  elle liste les **outils typiques suivants**, un clic ouvre la recherche.

Le modèle peut être modifié ou retiré à tout moment via **Modifier**.

## Dossiers restreints (besoin d'en connaître)

Par défaut, toutes les personnes de votre autorité voient tous les dossiers.
Activez **« Accès »** lors de la création ou de la modification d'un dossier
pour le **restreindre** : seuls **l'auteur**, la **personne assignée**, les
**membres** inscrits et **l'administration** de votre autorité le voient alors.
Pour tous les autres, le dossier n'existe pas — il est absent des listes, des
recherches, des alertes et des surveillances, et son lien répond « introuvable ».

- Seule la personne qui a créé le dossier, ou l'administration, peut modifier
  l'accès. Les membres travaillent dans le dossier mais ne peuvent pas élargir
  le cercle.
- Les membres sont des noms d'utilisateur. Des collègues qui ne se sont encore
  jamais connectés peuvent être ajoutés.
- Chaque modification de l'accès figure dans le **« Journal des recherches »**
  du dossier.
- L'administration est incluse à dessein : quelqu'un doit pouvoir réassigner
  un dossier lorsque l'enquêteur n'est plus là.

## Sauvegarder des preuves

Un résultat est un lien — si la page est supprimée, il ne reste que
l'affirmation. **« Sauvegarder la page »** (dans la fiche d'un résultat qui a
une page source, ou dans l'onglet **« Preuves »** pour toute adresse saisie)
charge la page dans un vrai navigateur et dépose, dans le stockage de votre
autorité :

- une **capture d'écran de la page entière** (PNG),
- une **archive** de la page avec ses images et sa mise en forme (MHTML —
  s'ouvre dans Chrome ou Edge),
- l'**empreinte SHA-256** de chaque fichier, l'adresse finale après
  redirections, le statut HTTP, l'heure, qui a sauvegardé et si Tor a été
  utilisé.

Les pages `.onion` sont chargées via Tor et peuvent prendre plus d'une minute.
Les adresses internes sont refusées. L'empreinte permet à quiconque de vérifier
plus tard qu'un fichier téléchargé est exactement celui qui a été sauvegardé —
sous Windows : `certutil -hashfile fichier.mhtml SHA256`. Chaque sauvegarde
figure aussi dans le **« Journal des recherches »**. L'exploitant de la
plateforme ne connaît que les empreintes, jamais la page.

---

Suite : **[Lancer une recherche →](03-searching.md)** · Retour : **[Premiers pas](01-getting-started.md)**
