# Suivre l'évolution d'un dossier en cours

Dans un dossier qui reste ouvert pendant des semaines, la question est rarement
« qu'avons-nous » — c'est **« qu'y a-t-il de nouveau depuis la dernière fois »**.
Deux fonctions y répondent : l'onglet *Nouveau depuis la dernière exécution*
pour une recherche que vous avez lancée vous-même, et la surveillance pour
celles qui s'exécutent d'elles-mêmes.

## « Nouveau depuis la dernière exécution »

Ouvrez un dossier et choisissez l'onglet **Nouveau depuis la dernière
exécution**. Il montre ce que la recherche la plus récente a ajouté : nouveaux
résultats, nouvelles relations, et l'exécution dont ils proviennent.

Cet onglet existe parce que relancer une recherche est volontairement
*idempotent* — un résultat qui figurait déjà dans le dossier conserve son
identité au lieu d'être ajouté une seconde fois. C'est le bon comportement, et
c'est aussi la raison pour laquelle une nouvelle analyse donne l'impression que
rien ne s'est passé. C'est dans cette vue que la différence devient visible.

**Ce qui compte comme nouveau.** La limite est le moment où la recherche a
démarré ; tout ce qui a été enregistré dans votre dossier après ce moment est
un ajout. Un résultat qui existait déjà et a simplement été reconfirmé
n'apparaît **pas**. Cela compte davantage qu'il n'y paraît : chaque nouvelle
analyse met à jour la provenance des résultats existants, et les compter comme
des découvertes ferait passer chaque exécution pour une percée.

### Ce qu'elle ne vous dit pas

**Les disparitions ne sont pas suivies, et la vue le dit.**

Si une entrée sur un site de fuites disparaît ou si un profil est supprimé, cela
n'apparaîtra pas ici. La raison est de l'ordre de l'honnêteté plutôt que de la
technique : un outil qui a simplement échoué et une véritable suppression
(takedown) sont indiscernables depuis l'intérieur de la plateforme. Signaler la
seconde alors qu'il s'agissait en réalité du premier serait pire que de ne rien
dire — la plateforme ne dit donc rien, et le dit ouvertement.

Si une disparition est importante pour votre dossier, la méthode fiable reste
la même que toujours : conservez la preuve au moment où vous la voyez (capture
d'écran, export, lien vers la preuve) plutôt que de compter sur l'outil pour
remarquer son absence plus tard.

## Surveillance

Là où la vue des différences répond à « qu'a ajouté ma dernière exécution », la
surveillance répond à « prévenez-moi quand quelque chose change pendant que je
ne regarde pas ».

Placez une surveillance sur un dossier : la plateforme relance la recherche
selon un calendrier et déclenche une alerte lorsque le résultat change. La mise
en place et la gestion sont décrites sous
[Surveillance et alertes](07-monitoring-and-alerts.md).

Les deux fonctionnent bien ensemble : la surveillance vous dit *que* quelque
chose a bougé, la vue des différences vous montre *quoi*.

## Une routine pratique

Pour un dossier faisant l'objet d'une enquête active :

1. Relancez la recherche, ou laissez la surveillance le faire.
2. Ouvrez **Nouveau depuis la dernière exécution** — c'est le chemin le plus
   court vers ce qui a changé.
3. Traitez les ajouts de haut en bas ; ils sont triés selon le même score de
   pertinence que partout ailleurs (voir
   [Évaluer les résultats](12-assessing-findings.md)).
4. Marquez ceux qui comptent, notez pourquoi, et laissez le reste de côté — il
   reste dans le dossier et ne coûte rien.
5. Générez un rapport lorsque vous avez besoin d'un instantané. Le rapport
   décrit toujours le dossier dans son état actuel, pas seulement les
   différences.

> **Relancer un ancien dossier vaut la peine en soi, une fois.** Les résultats
> collectés avant que votre instance ne dispose des cotations et des liens vers
> la preuve restent non cotés jusqu'à ce que leur source soit à nouveau
> interrogée. Une seule nouvelle analyse les complète — sans créer de doublons,
> car l'identité est stable.
