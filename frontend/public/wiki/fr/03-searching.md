# Lancer une recherche

La recherche est le flux de travail central : vous fournissez à la plateforme un
**indicateur** (un nom d'utilisateur, une adresse e-mail, un domaine, une IP, un
numéro de téléphone, une adresse crypto, un pseudo Telegram, …), elle exécute
les **modules** pertinents, et les résultats construisent le graphe du dossier.

Vous pouvez lancer une recherche depuis la page **Recherche** ou depuis l'onglet
**« Nouvelle recherche »** à l'intérieur d'un dossier. Dans un dossier, les
résultats actualisent le graphe sur place ; depuis la page autonome, vous
obtenez une URL de progression que vous pouvez mettre en signet.

## Par où commencer : la page « Situation »

Si vous n'avez pas encore de sélecteur, ouvrez **Situation** dans le menu. Elle
liste des domaines délictuels tirés de rapports de situation publics — le
rapport annuel de fedpol, *La sécurité de la Suisse* du SRC, Europol —, chaque
fiche indiquant sa source et sa date.

Cliquez sur **« Reprendre »** pour un thème et le formulaire de recherche s'ouvre
prérempli avec le terme et une restriction judicieuse (p. ex.
*Rockerkriminalität* + *Schweiz*). Rien ne s'exécute tant que vous n'avez pas
appuyé sur **Démarrer la recherche** — vous pouvez d'abord modifier le terme, la
restriction et les modules.

> **Ce qu'est le catalogue, et ce qu'il n'est pas.** Il décrit des *domaines
> délictuels*, pas des suspects. Il ne désigne aucune organisation comme une
> menace et ne fonde aucun soupçon ; chaque affirmation appartient à la source
> citée, pas à cet outil. Les entrées sont des points de départ de recherche.

Le catalogue est un fichier (`threat-catalog/catalog.json`) que vos
administrateurs peuvent compléter ou corriger à tout moment — sans mise à jour
logicielle. Adressez-vous à eux s'il manque un domaine délictuel pertinent pour
votre travail.

## Pas à pas

1. **« Terme de recherche / Indicateur »** — saisissez l'élément sur lequel vous
   enquêtez. Le texte indicatif montre l'idée : *« ex. anonymous99,
   max@example.com, 1.2.3.4, example.com, sha256:… »*.
2. **« Type »** — choisissez comment ce terme doit être interprété (nom
   d'utilisateur, e-mail, domaine, IP, URL, hash, téléphone, adresse
   Bitcoin/Ethereum, les types Telegram, invitation Discord, **URL d'image**,
   téléphone ou mot-clé). C'est le choix déterminant — il décide quels modules
   peuvent s'exécuter. Voir la liste complète dans
   [Référence](09-reference.md#query-types).
3. **« Attribuer au dossier »** — choisissez le dossier (ou cliquez sur
   **« Nouveau »** pour en créer un). À l'intérieur d'un dossier, ce champ est
   déjà rempli.
4. **« Modules »** — cochez les collecteurs à exécuter. **Seuls les modules qui
   comprennent le type choisi sont affichés**, et ils sont sélectionnés
   automatiquement lorsque vous changez de type. Survolez un module pour voir
   quels outils il va exécuter. Si aucun module ne prend en charge le type, vous
   verrez *« Aucun module disponible pour le type … »*.
5. Cliquez sur **« Démarrer la recherche »** (le bouton devient *« Recherche en
   cours... »*).

### Playbooks — partir de l'infraction plutôt que de la liste des modules

Au-dessus des cases à cocher des modules se trouvent les **playbooks** : des
préréglages pour les types d'infraction courants — rançongiciel, hameçonnage,
commerce darknet, fraude / faux site, fraude crypto, sextorsion,
infrastructure. En choisir un coche les modules qui valent la peine d'être
exécutés pour ce genre d'affaire.

Il s'agit de pure configuration : un playbook ne fait rien que vous ne
pourriez faire à la main, il vous épargne simplement de décider lesquels d'une
douzaine de modules méritent leur temps d'exécution. Deux détails permettent de
s'y fier :

* Vous ne voyez que les playbooks pour lesquels votre autorité dispose d'une
  licence — un préréglage ne peut jamais proposer un module qui serait ensuite
  refusé.
* Chaque entrée indique si elle convient au **type** actuellement saisi, de
  sorte qu'un préréglage conçu pour des domaines n'est pas proposé pour un nom
  d'utilisateur.

Vous pouvez ensuite ajuster les coches. Le playbook est un point de départ, pas
un réglage.

## Recherche avancée : regarder avant d'enregistrer

La recherche ordinaire ajoute au dossier tout ce qu'elle trouve. C'est ce que
vous voulez lorsque vous ouvrez une piste, et la mauvaise chose lorsque vous en
suivez une — un seul pivot trop large peut noyer un dossier sous le bruit.

La **recherche avancée** (le panneau *Recherche avancée*, accessible aussi
depuis n'importe quel nœud du graphe) exécute la même collecte mais
**n'enregistre rien**. Vous obtenez les candidats sous forme d'aperçu, ceux déjà
présents dans votre dossier étant signalés, et vous cochez ceux à conserver.
Seuls ceux-ci sont écrits.

C'est voulu, et pas seulement par souci d'ordre : **la décision de relier un
résultat à un autre est prise par une personne.** La plateforme vous montrera
qu'un nom d'utilisateur apparaît sur onze sites ; elle ne décidera pas à votre
place qu'il s'agit du même individu. Dans un dossier, c'est cette distinction
qui doit tenir.

Utilisez-la chaque fois que vous pivotez depuis un résultat plutôt que depuis
un nouveau sélecteur — ce qui, après la première recherche, est le cas la
plupart du temps.

> **Champs facultatifs.** *« E-mail (facultatif) »*, *« Téléphone
> (facultatif) »*, *« Priorité (facultatif) »* et *« Note (facultatif) »* sont
> des commodités : la note est ajoutée à la description du dossier avec un
> horodatage et votre nom. La recherche elle-même n'utilise que le champ
> principal *« Terme de recherche »*.

## Restreindre une recherche par mot-clé (« Restreindre »)

Un terme comme **Crimson Wolves** renvoie des résultats du monde entier. Lorsque
le type de recherche est **Mot-clé**, un champ **« Restreindre (facultatif) »**
apparaît, dans lequel vous pouvez choisir — ou saisir librement — des termes de
restriction :

* **Région** — Schweiz, Deutschschweiz, Romandie, Ticino
* **Canton** — les 26, sous leur nom officiel (Zürich, Genève, Ticino …)
* **International** — Europa, International, pays voisins
* **Domaine délictuel** — Drogenhandel, Waffenhandel, Geldwäscherei …
* **tout ce que vous saisissez vous-même** — une ville, un quartier, un milieu

Chaque terme de restriction lance **une recherche supplémentaire** avec ce terme
ajouté. « Crimson Wolves » plus « Schweiz » et « Zürich » lance trois recherches :
le terme seul, `Crimson Wolves Schweiz` et `Crimson Wolves Zürich`. Le champ indique
combien de recherches votre sélection coûtera *avant* que vous ne lanciez.

Tous les résultats aboutissent dans le **même dossier**. Dans le graphe, vous
verrez le terme de base se ramifier vers les termes restreints, de sorte que
vous pouvez distinguer **quelle restriction a produit quel résultat**. Les
services trouvés par plus d'une recherche n'apparaissent qu'une fois, pas
plusieurs.

> **Pourquoi la limite de cinq ?** Chaque recherche interroge chaque outil de
> chaque module sélectionné. Cinq termes de restriction sur quatre outils
> représentent déjà deux douzaines de requêtes, et plusieurs sources nous
> limitent à ce volume. Peu de termes de restriction bien choisis donnent de
> meilleurs résultats que beaucoup de termes larges.

> La restriction ne s'applique qu'aux recherches par **mot-clé**. Ajouter
> « Zürich » à une adresse e-mail ou à une adresse Bitcoin produirait un
> sélecteur qui ne correspond à rien ; le champ est donc masqué pour ces types.

## Finalité / base légale

Le champ **« Finalité / base légale »** consigne la raison d'une recherche —
numéro de dossier, ordonnance, mandat. Il est enregistré **uniquement dans le
journal des recherches de votre autorité** (onglet **« Journal des
recherches »** du dossier), jamais chez l'exploitant de la plateforme ;
celui-ci apprend seulement *qu'une* finalité a été indiquée.

- Dans un dossier, la dernière finalité utilisée est proposée à nouveau.
- Si votre administration a activé *« Exiger une finalité pour chaque
  recherche »* (Admin → Paramètres), une recherche sans finalité est refusée.
  Si le journal des recherches de votre autorité est inaccessible à ce
  moment-là, la recherche **n'est pas lancée** — ce qui ne peut être
  journalisé ne s'exécute pas.
- Il en va de même lors de la création d'une **surveillance** ; ses recherches
  automatiques renvoient à la finalité indiquée à la création.

## Suivre la progression

La recherche est distribuée **en parallèle** à tous les outils correspondants.
Un tableau **« État des outils »** en direct est actualisé toutes les 3 secondes,
avec une ligne par outil :

**Module · Outil · Statut · Résultats · Arêtes · Durée · Erreurs**

Il se termine par **« Terminée »**, **« Terminée (partielle) »** (un outil a
rencontré une erreur — p. ex. une clé API manquante), **« Échec de la
recherche »** ou **« Interrompue »** (vous l'avez arrêtée — voir ci-dessous).
Sur la page de progression autonome, vous obtenez aussi les compteurs
**« Entités découvertes »** et **« Connexions »** ainsi qu'un bouton **« Ouvrir
le dossier »**.

### Arrêter une recherche

Si une recherche prend trop de temps, ou si vous avez saisi le mauvais
sélecteur, arrêtez-la depuis la page de progression avec **« Arrêter la
recherche »**.

> **Tout ce qui a déjà été trouvé est conservé.** Les résultats sont écrits
> dans le dossier au fur et à mesure de leur arrivée — l'arrêt ne met fin
> qu'aux outils encore en cours. La barre de progression reste donc là où la
> recherche est réellement arrivée et n'affiche délibérément **pas** 100 % :
> « interrompue » n'est pas « terminée », et un dossier doit garder cette
> différence lisible.
>
> **Un outil peut encore tourner brièvement.** L'arrêt met fin à notre attente
> de la source ; le module s'en aperçoit à son étape suivante. C'est sans
> conséquence — tout ce qui arrive ensuite appartient à une recherche terminée
> et n'est plus pris en compte.

> **La barre de progression reflète le travail réel** — elle se remplit à
> mesure que chaque outil se termine (p. ex. *7 outils sur 11 terminés*), pas
> selon une estimation fixe.
>
> **Les résultats sont enregistrés à leur arrivée.** Les résultats sont écrits
> dans le dossier **progressivement, module par module** — le graphe se remplit
> pendant la recherche, vous n'avez pas à attendre l'outil le plus lent.
>
> **Vous pouvez quitter la page.** La recherche s'exécute sur le serveur ;
> changer d'onglet, naviguer ailleurs ou **actualiser le navigateur** ne
> l'arrête pas et ne fait pas perdre la progression — rouvrez le dossier (ou
> l'URL de progression) et elle est toujours là, en cours d'actualisation.

> **Un outil portant la mention « key not set » n'est pas un échec** — cette
> seule source a simplement besoin d'une clé API que votre exploitant n'a pas
> configurée. Tous les autres outils se sont exécutés. De même, **zéro résultat
> est une réponse valable** (p. ex. une adresse e-mail qui n'apparaît dans
> aucune fuite).

## Ce que vous obtenez

Chaque résultat devient une **entité** (un nœud) dans le dossier, et les
relations entre elles deviennent des **arêtes**. Les modules réussis
conservent leurs résultats même si un autre module a rencontré une erreur.
Rendez-vous dans l'onglet **« Graphe réseau »** pour explorer ce qui est
revenu.

## Actualités & RSS

**Actualités & RSS** dans le menu correspond à la recherche ordinaire avec le
module d'actualités présélectionné. Elle effectue une recherche en texte
intégral dans les flux gérés par votre exploitant — organes fédéraux, police,
médias et sources cyber — et renvoie chaque résultat sous forme de nœud
portant **la date, la source et le type de source**.

Le type de source compte lorsque vous lisez le graphe : un communiqué
`authority` et un article `media` sont tous deux des pistes légitimes, mais ils
n'ont pas le même poids probant. Les sources officielles reçoivent en outre une
confiance plus élevée.

La restriction fonctionne ici aussi : *Rockerkriminalität* + *Schweiz*
recherche donc les deux termes ensemble dans les flux. Et comme le module
d'actualités réagit aux mots-clés simples, un thème repris depuis la page
**Situation** interroge également les sources d'actualités, sans étape
supplémentaire.

> **Ce qu'il ne fait pas.** Il recherche dans les entrées publiées par un
> flux — titre et chapeau —, pas dans le texte intégral des PDF liés. Les flux
> ne remontent en outre qu'aussi loin que la source les publie (généralement
> quelques années). Une absence de résultat signifie « pas dans ces flux »,
> jamais « ne s'est pas produit ».

Il manque une source ? Votre exploitant l'ajoute sous **Paramètres → Flux RSS**
dans la console Admin global ; elle s'applique dès la recherche suivante.

---

Suite : **[Modules & outils →](04-modules-and-tools.md)** · Retour : **[Travailler avec les dossiers](02-cases.md)**
