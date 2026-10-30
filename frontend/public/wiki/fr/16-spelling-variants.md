# Variantes d'écriture

Les enquêtes en matière de cybercriminalité commencent rarement par le nom d'une
personne. Elles commencent par un **pseudo** — et un pseudo n'est jamais écrit
deux fois de la même manière. Le même acteur est `d4rkc1ph3r` sur un forum,
`darkcipher` sur le suivant, `dark_cipher` sur un troisième, et `darkcipher1`
après un bannissement.

Une recherche portant uniquement sur la chaîne exacte saisie perd le résultat
dès qu'un seul caractère est substitué, sans que rien ne le signale. La
plateforme recherche donc aussi des variantes d'orthographe.

## Ce qui est désormais recherché en plus de votre saisie

| Motif | Exemple |
|---|---|
| Leetspeak | `d4rkc1ph3r` ↔ `darkcipher` |
| Séparateurs | `dark_cipher`, `dark.cipher`, `dark-cipher` |
| Chiffres finaux | `darkcipher1` → `darkcipher` |
| Cyrillique → latin | `Пётр` → `petr` |

Cela fonctionne **dans les deux sens** : rechercher `darkcipher` trouve aussi
`d4rkc1ph3r`, et inversement.

## La règle qui compte : un candidat n'est pas une identité

Un résultat obtenu par une variante signifie :

> Il existe un compte dont l'écriture correspond à votre recherche.

Cela ne signifie **pas** :

> Il s'agit de la même personne.

`darkcipher` sur Reddit et `d4rkc1ph3r` sur XSS peuvent être deux personnes qui
apprécient toutes deux ce mot. La plateforme les maintient donc visiblement
séparés :

* les résultats de variantes portent **`match_type: variant`** et indiquent
  l'écriture qui les a produits
* ils sont **évalués plus bas** qu'un résultat direct
* leur relation dans le graphe est `possible_handle_variant` ou
  `possible_account_of` — jamais `is_account_of`
* une remarque au-dessus de la liste des résultats indique combien de résultats
  proviennent de variantes

**Ce qui transforme un candidat en résultat, c'est un second signal :** le même
mot de passe, la même clé PGP, le même forum, le même portefeuille, les mêmes
habitudes d'écriture. C'est à cela que sert la corroboration (voir *Évaluer les
résultats*). Consignez le raisonnement dans le champ de notes du nœud — il
apparaît à côté du résultat dans le rapport.

## Où cela s'applique

**Automatiquement, sans coût**

*Acteurs connus* (`threat_actor_check`) vérifie votre pseudo et ses variantes
dans un index de 830 000 noms d'utilisateur provenant de 25 forums criminels.
L'index est local ; la recherche de variantes ne coûte donc rien et prend
quelques millisecondes.

**Sur demande, parce que cela prend du temps**

*Balayage de pseudo (variantes d'écriture)* dans le module **Alias** interroge
environ 600 plateformes — une fois par écriture. Une exécution prend donc une à
trois minutes au lieu de cinquante secondes. Choisissez cet outil délibérément
lorsqu'un pseudo est au centre d'un dossier.

Le gain est réel : lors des tests, `d4rkc1ph3r` seul a renvoyé 8 comptes ; avec
les variantes, 54.

## Limites à connaître

**Les séparateurs peuvent être supprimés, pas inventés.** `tony-stark` trouve
`tonystark`. L'inverse ne fonctionne pas — impossible de savoir que la coupure
se situe après `tony` plutôt qu'après `to`. **En cas de doute, recherchez
l'écriture la plus séparée** ; elle trouve davantage.

**Les pseudos courts n'ont pas de variantes.** En dessous de quatre caractères,
chaque résultat serait du bruit : `b0b` pour `bob` est presque certainement une
autre personne.

**Le nombre d'écritures est plafonné.** Le balayage de pseudo en teste quatre au
maximum. C'est voulu — une liste de variantes illimitée produit des candidats
auxquels aucun enquêteur ni aucune enquêtrice n'aurait pensé, et c'est
précisément de là que viennent les fausses pistes.

## Noms de personnes

Les noms de personnes obéissent à une autre mécanique que les pseudos : le
contrôle des sanctions compare **des mots entiers, dans
n'importe quel ordre**. « Vladimir Putin » et « Putin Vladimir » donnent
désormais le même résultat — auparavant, l'une des deux listes officielles
disparaissait selon la manière dont vous saisissiez le nom, parce que l'UE
écrit « Vladimir PUTIN » et les États-Unis « PUTIN, Vladimir ». Le contrôle
reste expressément non approximatif : seuls des **mots entiers** sont comparés,
de sorte que personne ne se retrouve par erreur sur une liste de sanctions.
