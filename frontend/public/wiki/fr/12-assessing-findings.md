# Évaluer les résultats

Une recherche portant sur une douzaine de modules renvoie couramment plusieurs
centaines de nœuds. La collecte n'a jamais été la partie difficile — décider
lesquels des vingt comptent vraiment, si. Cette page explique les trois
mécanismes que la plateforme met à votre disposition à cet effet et, tout aussi
important, ce que chacun d'eux **ne** prétend **pas**.

## La cotation (Admiralty)

Chaque résultat porte une cotation à deux caractères, par exemple **B2**. Il
s'agit de l'échelle Admiralty de l'OTAN, qui répond à deux questions distinctes
qu'un unique chiffre de « confidence » mélangeait auparavant.

**La lettre — quelle est la fiabilité de la source ?** Déclarée par outil, car
seul l'auteur de l'outil sait quel type d'affirmation celui-ci produit. Un
résultat issu d'un registre de certificats est un fait d'une autre nature
qu'un résultat trouvé sur une page de profil extraite par scraping, même si
les deux ont « fonctionné ».

| | Signification |
|---|---|
| **A** | Entièrement fiable — registre faisant foi ou source primaire |
| **B** | Habituellement fiable |
| **C** | Assez fiable |
| **D** | Habituellement peu fiable |
| **E** | Non fiable |
| **F** | **Ne peut être évaluée** — l'outil ne déclare rien |

**F est une lacune assumée, pas une mauvaise note.** Cela signifie que personne
n'a évalué cette source ; ne la lisez donc pas comme « élément de preuve
faible », mais comme « non évaluée ».

**Le chiffre — quelle est la crédibilité de cette affirmation précise ?**
Déterminé par la plateforme pour chaque résultat, car seule la plateforme voit
si d'autres outils ont abouti à la même conclusion.

| | Signification |
|---|---|
| **1** | Confirmée par d'autres sources — **deux outils indépendants ou plus ont signalé la même chose** |
| **2** | Probablement vraie |
| **3** | Possiblement vraie |
| **4** | Douteuse |
| **6** | Ne peut être évaluée |

**Le 5 (« improbable ») n'est jamais attribué.** Rien dans la chaîne de collecte
ne permet de justifier d'argumenter activement contre un résultat ; la
plateforme ne prétend donc pas pouvoir le faire.

Une subtilité à connaître : lorsque plusieurs outils signalent le même nœud, la
lettre affichée correspond à la **meilleure** fiabilité parmi eux. Si un
registre et un scraper renvoient tous deux une valeur, c'est la parole du
registre qui détermine la valeur du résultat — une seconde source faible peut
accroître la crédibilité, mais elle ne peut pas abaisser la fiabilité.

## Confirmation croisée

Sous la cotation, vous voyez les outils qui ont signalé le même résultat de
manière indépendante, par exemple **✓ 3**. Survolez l'indication avec la souris
pour voir lesquels.

C'est le signal le plus fort que produit le système, et c'est la raison pour
laquelle le chiffre peut atteindre **1**. Deux propriétés le rendent digne de
confiance :

* Il repose sur l'**identité canonique** du résultat, et non sur son
  orthographe exacte — deux façons d'écrire la même adresse comptent toujours
  comme une concordance.
* Il **s'accumule d'une recherche à l'autre**. Un outil qui confirme un nœud des
  mois plus tard est ajouté à la liste au lieu de la remplacer. C'est
  précisément cet historique qui mérite d'être conservé.

Dans le graphe, un nœud signalé par deux outils indépendants ou plus est
dessiné avec un **double anneau**. La taille d'un nœud dépend du nombre de ses
connexions, ce qui fait visuellement dominer la source la plus bruyante ;
l'anneau sert de contrepoids en signalant le résultat le mieux étayé plutôt que
le plus connecté.

## Classement par pertinence

La liste des résultats est triée selon un score de pertinence construit à
partir de quatre signaux :

| Signal | Poids | Pourquoi |
|---|---|---|
| Confirmation croisée | 40 % | Une concordance indépendante est le signal le plus difficile à falsifier |
| Fiabilité de la source | 25 % | La lettre Admiralty |
| Position dans le graphe | 20 % | Degré de connexion du nœud |
| Distance par rapport à votre sélecteur | 15 % | Nombre de sauts depuis ce que vous avez effectivement recherché |

Le score est **recalculé à chaque fois, jamais enregistré**. Marquez un faux
positif ou lancez un autre outil, et l'ordre change immédiatement. Une colonne
enregistrée serait périmée dès le clic suivant, et vous n'auriez aucun moyen de
savoir quelles lignes sont à jour.

Le rapport utilise le même score de la même manière : l'ordre que vous voyez à
l'écran est celui dans lequel le PDF argumente. Il n'existe délibérément qu'un
seul classement dans le système.

## Éléments de preuve

Lorsqu'un outil a indiqué une source, le résultat porte un **lien vers la
preuve** — la page d'où provient l'affirmation — ainsi que le moment où la
source l'a affirmée (`observed`, observé), distinct du moment où il a été
enregistré dans votre dossier (`found`, trouvé). Pour les sources qui évoluent
rapidement, comme les sites de fuites, les pastes et Telegram, c'est le moment
de l'observation qui compte du point de vue probatoire.

> **Les résultats plus anciens peuvent ne pas avoir de lien vers la preuve.**
> Une colonne ne peut être remplie que par un outil qui renvoie la valeur ; les
> lignes collectées avant que votre instance ne gère la provenance restent donc
> vides jusqu'à ce que cette source soit interrogée à nouveau. Il s'agit d'une
> lacune dans la traçabilité, pas d'une erreur dans le résultat — et relancer la
> recherche la comble sans créer de doublons.

## Les emplacements réservés ne sont pas des résultats

Certains nœuds n'existent que pour maintenir la cohérence du graphe : une
relation a été signalée, mais son autre extrémité n'a jamais été confirmée en
tant que telle. Ces nœuds sont marqués comme emplacements réservés, sont
comptés séparément et n'apparaissent jamais dans les rapports ni dans les
exports. Personne ne les a affirmés ; ils ne prouvent donc rien.

La seule exception est le nœud correspondant au terme que vous avez recherché.
Il est techniquement virtuel, mais il constitue le sélecteur faisant l'objet de
l'enquête et sert d'ancrage à la majeure partie du graphe ; il est donc traité
partout comme réel.

## Que faire de tout cela

Un ordre de travail pratique :

1. Triez par pertinence (le réglage par défaut) et lisez d'abord le haut de la
   liste.
2. Privilégiez les résultats dont le **chiffre est 1** — ce sont ceux derrière
   lesquels se tient plus d'un outil.
3. Ouvrez le lien vers la preuve avant de vous fier à quoi que ce soit. La
   cotation vous indique quel poids une source mérite ; elle ne vous dit jamais
   que le résultat est vrai.
4. Marquez comme pertinent ce qui compte (l'étoile) et marquez les faux positifs
   comme tels. Les deux influencent directement le classement et le contenu du
   rapport.
5. Consignez le *pourquoi* dans le champ de note du nœud. La cotation est
   l'évaluation de la plateforme ; la note est la vôtre, et c'est elle qui aura
   encore un sens dans six mois.

Voir aussi : [Lire le graphe](06-reading-the-graph.md) ·
[Rapports](08-reports.md) · [Exporter](14-exporting.md)
