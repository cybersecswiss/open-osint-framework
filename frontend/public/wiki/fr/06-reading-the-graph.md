# Lire le graphe

L'onglet **« Graphe réseau »** représente tout le contenu d'un dossier sous
forme de réseau : les **nœuds** sont des entités (personnes, comptes, canaux,
adresses, messages, …) et les **arêtes** sont les relations entre elles. La
**couleur** d'un nœud indique le type d'entité ; sa **taille** augmente avec
le nombre de ses connexions.

## Commandes (barre latérale gauche)

- **« Disposition »** — la manière dont les nœuds sont agencés : un arbre en
  largeur (par défaut), *Force (fcose)*, *Concentrique*, *Cercle*, *Grille*
  ou *Force (cose)*.
- **« Limite de rendu »** — les grands dossiers peuvent compter des milliers
  de nœuds ; ce réglage limite le nombre de nœuds dessinés simultanément
  (100 par défaut, jusqu'à 1000). Le badge affiche *visibles / total*.
- **« Afficher toutes les étiquettes »** — étiqueter chaque nœud au lieu de
  n'afficher l'étiquette qu'au survol.
- **« Filtrer par type »** — c'est aussi la **légende** : une entrée colorée
  par type d'entité, avec son nombre. Décochez un type pour le masquer.
- **« Ajuster »** cadre l'ensemble · **« Réorganiser »** relance l'animation
  de disposition · **« Capture d'écran »** télécharge un PNG de la vue
  actuelle.
- En bas à droite, les commandes de **zoom** (boutons + curseur,
  10–400 %) ; la molette de la souris permet aussi de zoomer.

## Interagir avec les nœuds

- **Clic** sur un nœud → son **panneau de détails** s'ouvre à droite.
- **Double-clic** sur un nœud → **« Étendre la recherche depuis ici »** : la
  plateforme lance une *nouvelle* recherche à partir de ce nœud (p. ex. un
  double-clic sur un canal Telegram lance une recherche de canal) et place
  les résultats dans le même dossier.
- **Clic droit** sur un nœud → un menu : *« Afficher les détails »*,
  *« Étendre la recherche depuis ici »*, *« Marquer comme pertinent »* /
  *« Retirer la marque »*, *« Ajouter à la surveillance… »*, *« Retirer comme
  faux positif »*, ainsi que *« Copier l'étiquette »* / *« Copier l'ID de
  l'entité »*.
- **Survolez** un nœud pour le mettre en évidence avec ses connexions ;
  survolez une arête mise en évidence pour lire son **libellé de relation**
  (p. ex. `MEMBER_OF`, `FORWARDED_FROM`). Les arêtes sont orientées (pointes
  de flèche).
- Les nœuds **pertinents** reçoivent une bordure dorée et un halo.

Graphe vide ? *« Aucune donnée — lancez une recherche pour construire le
réseau »*.

## Le panneau de détails du nœud

La sélection d'un nœud affiche :

- Des étiquettes d'en-tête : le **type d'entité**, la **plateforme** (le cas
  échéant), un pourcentage de **confiance** et une étiquette dorée
  **★ pertinent** si le nœud est marqué.
- L'**étiquette** du nœud, une **URL** cliquable si elle existe, puis un
  tableau de tous les champs de données renvoyés par la source (les URL
  deviennent des liens, les hash s'affichent avec un bouton de copie, les
  listes sont rendues sous forme de puces).
- Des boutons d'action : **« Activer la surveillance »**, marquer / retirer
  la marque **pertinent** et **« Retirer comme faux positif »**.

## Lire la qualité sur le graphe

Deux indices visuels portent l'évaluation d'un résultat par la plateforme :

- **Un double anneau** signifie que deux outils indépendants ou plus ont
  signalé ce nœud. C'est le signal le plus fort que le système produit. Notez
  que la **taille** d'un nœud suit le nombre de ses connexions, ce qui rend
  visuellement dominante la source la plus bruyante — l'anneau fait
  contrepoids en signalant le nœud le mieux *étayé* plutôt que le plus
  chargé.
- **La pastille de cotation** (p. ex. `B2`) sur la fiche du nœud est la
  cotation Admiralty : la fiabilité de la source sous forme de lettre, la
  crédibilité de cette affirmation précise sous forme de chiffre.

Les deux sont expliqués en détail sous
[Évaluer les résultats](12-assessing-findings.md) — cela vaut la peine de
le lire une fois, car les cotations changent la manière dont vous devriez
établir vos priorités.

La fiche du nœud comporte aussi un **champ de note**. Ce que vous y écrivez
reste attaché au résultat, est repris dans le rapport et dans l'export, et
est stocké dans la base de données de votre propre autorité. Utilisez-le pour
le raisonnement que la cotation ne peut pas saisir : pourquoi vous pensez que
ce compte appartient à la même personne, ce que vous avez déjà vérifié, ce
qui reste à vérifier.

## Travailler le dossier

Un bon rythme : lancer une recherche → ouvrir **Résultats** et travailler de
haut en bas (la liste est triée par pertinence) → **cliquer** sur les nœuds
intéressants pour lire les détails et le lien vers la preuve → approfondir
avec la **recherche avancée**, afin de choisir vous-même ce qui est ajouté →
**marquer comme pertinents** ceux qui comptent, **retirer** les faux positifs
et **noter** pourquoi. Répétez jusqu'à ce que le tableau soit complet, puis
produisez un [rapport](08-reports.md) ou un [export](14-exporting.md).

Lorsque vous revenez à un dossier, commencez plutôt par
**[Nouveau depuis la dernière exécution](13-tracking-changes.md)**.

## Fusionner des nœuds

Lorsque deux nœuds désignent la même personne ou la même chose — deux noms
d'utilisateur d'une personne, deux graphies d'une société —, ouvrez l'un d'eux
et choisissez **« Fusionner… »**. Choisissez les autres ; ils se fondent dans
celui que vous avez ouvert :

- leurs **liens** sont transférés (un lien qui existerait alors en double n'en
  fait plus qu'un, avec les deux sources),
- leurs **sources** comptent pour le nœud restant, ce qui peut relever son
  évaluation,
- notes et adresse source sont reprises, leurs noms restent visibles comme
  **« Aussi connu comme »**,
- les **recherches futures** qui trouvent un nom fusionné le rattachent au nœud
  restant au lieu de le recréer,
- surveillances et alertes suivent.

Une fusion est irréversible et figure dans le **« Journal des recherches »**.
Pour seulement consigner un lien sans trancher l'identité, tracez plutôt un
lien.

## Même résultat dans d'autres dossiers

Si un résultat de ce dossier — une adresse e-mail, un nom d'utilisateur, un
portefeuille — figure aussi dans un **autre dossier de votre autorité**, une
barre jaune au-dessus des onglets le signale, et la fiche du nœud affiche
**« aussi dans 2026-… »** ; un clic ouvre ce dossier. Seuls les dossiers que
vous pouvez ouvrir sont mentionnés : un dossier restreint dont vous ne faites
pas partie n'apparaît jamais ici. La comparaison ignore majuscules/minuscules
et s'effectue dans le stockage de votre autorité.

---

Suite : **[Évaluer les résultats →](12-assessing-findings.md)** · Retour : **[Outils Telegram](05-telegram.md)**
