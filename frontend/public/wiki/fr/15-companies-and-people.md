# Entreprises & personnes

Tous les autres modules partent d'un sélecteur technique — un nom
d'utilisateur, un domaine, un hash, un wallet. Celui-ci part d'un **nom**, ce
qui constitue le véritable point d'entrée d'une affaire portant sur des
acquisitions, le contournement de sanctions ou des sociétés écrans.

Choisissez le type de requête **Raison sociale** ou **Nom de personne**, saisissez
le nom et cochez le module *Entreprises & personnes*. Les cinq outils
fonctionnent sans clé.

## À quelle question répond chaque outil

| Outil | La question à laquelle il répond | Cotation |
|---|---|---|
| **Registre suisse (FOSC)** | Cette entreprise existe-t-elle en Suisse, qui signe pour elle, depuis quelle adresse, et est-elle toujours inscrite ? | A |
| **Structure de groupe (GLEIF)** | À qui appartient-elle, que détient-elle, et sous quels autres noms est-elle enregistrée ? | A |
| **Contrôle des sanctions** | Ce nom figure-t-il sur les listes de sanctions de l'UE ou des États-Unis, et au titre de quel programme ? | A |
| **Liens Wikidata** | Qui la dirige, qui y détient une participation, qu'est-ce qui appartient encore au même groupe ? | C |
| **Annuaire suisse** | Où quelqu'un décroche-t-il physiquement le téléphone ? | B |

## Un exemple concret

Supposons que vous recherchiez la société (fictive) **Muster Trading SA** en
tant que *Raison sociale*. Une telle recherche renvoie typiquement :

* la **succursale de Genève** issue du registre du commerce — son IDE
  (`CHE-…`), son adresse, le registre cantonal où elle est inscrite et, le
  cas échéant, la date de sa **radiation** et son motif ;
* les **signataires nommément désignés**, par exemple un directeur disposant
  de la signature individuelle, avec sa nationalité et son lieu de domicile
  déclarés, ainsi que la phrase exacte publiée par le registre ;
* le **groupe** : la société mère étrangère avec son LEI, ses noms dans
  d'autres écritures et en variantes latines, ainsi que ses filiales ;
* la **direction** et les participations selon Wikidata.

Il s'agit de quatre types d'enregistrements différents concernant une seule
organisation, réunis dans un seul graphe — et chacun porte le lien dont il
provient.

## Lire les résultats avec attention

**L'entreprise est un enregistrement. Les personnes sont extraites d'un texte
rédigé.** Les publications du registre du commerce suisse désignent les organes
dans une phrase stéréotypée (« Signature individuelle a été conférée à … »,
« …, von Zug, in Bern, Mitglied des Verwaltungsrates »), et non dans un champ
structuré. L'outil les extrait avec prudence et joint la **phrase exacte** à
chaque personne qu'il produit, sous `register_statement`. Lisez cette phrase
avant de vous fier au nom. C'est aussi la raison pour laquelle les personnes
reviennent avec un degré de confiance inférieur à celui de l'entreprise à
laquelle elles sont rattachées.

**Un « no hit » (aucune correspondance) dans les sanctions ne vaut pas
blanchiment.** La correspondance est volontairement exacte : chaque mot de votre
requête doit figurer dans le nom inscrit. Cela évite d'incriminer la mauvaise
personne, mais signifie aussi qu'une orthographe **translittérée
différemment** ne sera pas trouvée. Иванов et Ivanov ne sont pas mis en
correspondance par la machine — cette déduction vous appartient, et c'est à vous
de la documenter. L'outil indique toujours combien de noms il a vérifiés.

**Wikidata est une piste, pas un enregistrement.** Cette base est alimentée par
une communauté. Servez-vous-en pour savoir *où chercher* — une filiale, une
présidence, un propriétaire — puis confirmez ce résultat dans un registre.

**L'absence d'une inscription dans l'annuaire ne prouve rien.** Un numéro non
publié est absent de tel.search.ch exactement comme un numéro inexistant.

## Place de ces outils dans un dossier

L'ordre naturel :

1. **D'abord le registre** — il vous fournit l'entité juridique, l'adresse et
   les personnes, le tout citable.
2. **La structure de groupe** — c'est généralement dans la société mère et les
   sociétés sœurs que se trouve la véritable contrepartie.
3. **Le contrôle des sanctions** sur chaque nom produit par les deux premières
   étapes, et pas seulement sur celui dont vous êtes parti.
4. **Ensuite, pivotez sur le plan technique** : l'adresse et les personnes
   alimentent des [recherches ordinaires](03-searching.md) — le domaine de
   l'entreprise dans `infra` et `theharvester`, le nom d'un organe dans les
   outils alias, le numéro de téléphone dans les outils de messagerie.

Le playbook **Contournement de sanctions / approvisionnement** configure tout
cela en un clic.

## Un mot sur la prudence

À partir d'ici, vous travaillez avec des **données personnelles concernant des
personnes réelles**. Qu'une personne soit inscrite comme organe dans un registre
du commerce est un fait public. Que cette même personne soit impliquée dans une
infraction est une allégation — la vôtre, et vous devez être en mesure de
l'étayer.

La plateforme sépare délibérément ces deux aspects : les outils collectent, un
être humain établit les liens, et le champ de note du nœud est l'endroit où
votre raisonnement a sa place. Utilisez-le. Dans six mois, ce sera la seule
trace de la raison *pour laquelle* vous avez relié deux résultats, et c'est
exactement ce qu'un dossier doit pouvoir montrer.

Voir aussi : [Évaluer les résultats](12-assessing-findings.md) ·
[Effectuer une recherche](03-searching.md) · [Exporter un dossier](14-exporting.md)
