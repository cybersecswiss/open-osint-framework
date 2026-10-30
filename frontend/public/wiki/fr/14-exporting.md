# Exporter un dossier

À côté du bouton de rapport, **Exporter** propose quatre formats lisibles par
machine. Utilisez le rapport lorsqu'une personne le lira ; utilisez un export
lorsque ce sera un *système* ou l'analyste d'une autre autorité.

| Format | À utiliser pour |
|---|---|
| **CSV** | Tableurs, votre propre gestion des dossiers, filtrage rapide |
| **CSV Maltego** | Importer le dossier sous forme de graphe dans Maltego |
| **Événement MISP** | Transmettre des indicateurs à un CERT / une plateforme de threat intelligence |
| **STIX 2.1** | La norme internationale d'échange d'informations sur les cybermenaces |

## Ce qui accompagne un résultat

Les quatre formats transportent la provenance, car un résultat sans son origine
n'est pas un élément de preuve exploitable pour le destinataire :

* l'**outil** qui l'a signalé,
* chaque outil qui l'a **confirmé de manière indépendante**,
* la **cotation Admiralty**,
* l'**URL de la source**, lorsque l'outil en a fourni une.

## Deux règles valables pour chaque export

**Les emplacements réservés ne quittent jamais la maison.** Les nœuds qui
n'existent que pour maintenir la cohérence du graphe sont exclus. Personne ne
les a affirmés, et une autorité partenaire qui les recevrait n'aurait aucun
moyen de les distinguer des résultats confirmés.

**Chaque export est journalisé.** La piste d'audit enregistre qui a exporté quel
dossier, quand, dans quel format, ainsi qu'une somme de contrôle SHA-256 du
contenu exact. Transmettre des résultats à une autre autorité est précisément
le genre d'acte qu'un dossier doit pouvoir prouver ultérieurement — y compris
prouver que ce que vous avez envoyé est bien ce que le destinataire a reçu.

## Particularités des formats à connaître

**MISP : les indicateurs ne sont pas activés par défaut.** Les attributs sont
envoyés avec `to_ids=false`, sauf si vous avez marqué le résultat comme
pertinent. `to_ids=true` indique au système destinataire de *bloquer un
indicateur ou d'alerter à son sujet* — des données OSINT non vérifiées ne
doivent pas arriver prêtes à se déclencher sur le réseau d'un partenaire.
Marquer un résultat comme pertinent revient à déclarer que vous l'avez vérifié ;
c'est ce qui fait basculer l'indicateur.

**STIX : les résultats hors du vocabulaire standard sont déclarés.** L'OSINT
produit des types d'objets pour lesquels STIX n'a pas d'équivalent. Plutôt que
de les omettre silencieusement ou de les étiqueter de façon erronée, ils sont
livrés en tant que `x-osint-entity`, et le bundle contient un objet `note`
indiquant combien sont concernés. Le destinataire peut alors décider quoi en
faire, au lieu d'ignorer leur existence.

**CSV et Maltego** transportent le même ensemble de champs ; la variante Maltego
utilise les noms de colonnes attendus par l'import de Maltego, de sorte qu'elle
se traduit en entités et en liens sans travail manuel.

## Ce qui est exporté

La même règle de sélection que celle du rapport :

* Si un élément du dossier est marqué comme **pertinent**, l'export contient
  exactement ces résultats.
* Sinon, il contient tout ce qui n'est pas marqué comme faux positif.

L'export suit donc votre tri. Si vous voulez la vue d'ensemble, retirez d'abord
les marques de pertinence ; si vous voulez le dossier tel que vous l'avez
évalué, laissez-les.

## Avant l'envoi

1. Vérifiez la cotation de ce que vous envoyez — voir
   [Évaluer les résultats](12-assessing-findings.md). La cotation **F** signifie
   que la source n'a jamais été évaluée, ce que l'analyste destinataire ne peut
   pas savoir si vous ne le précisez pas.
2. Demandez-vous si **tout** le contenu du fichier doit se retrouver entre les
   mains d'un tiers. L'export contient ce que contient votre dossier, notes
   comprises.
3. Gardez à l'esprit que le destinataire n'a pas accès à votre dossier. Ce que
   vous envoyez est tout ce qu'il en verra jamais ; les champs de provenance
   remplissent donc une fonction réelle.

Voir aussi : [Rapports](08-reports.md) · [Évaluer les résultats](12-assessing-findings.md)
