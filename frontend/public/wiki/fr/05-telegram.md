# Outils Telegram (approfondi)

Le module **Telegram (approfondi)** effectue une collecte Telegram
*authentifiée* via l'API officielle MTProto. Il lit bien davantage que
l'aperçu web public : historique complet des messages, membres et
administrateurs des canaux, transferts, médias, ainsi que des recherches
d'utilisateurs, de numéros de téléphone et de géolocalisation.

> **Disponibilité.** Ce module ne fonctionne que si votre exploitant a
> configuré une session Telegram active. Si elle est inactive, chaque outil
> renvoie dans les résultats une mention claire *« telegram module not
> authenticated »* au lieu de faire échouer toute la recherche. Demandez à
> votre exploitant de (ré)authentifier la session — voir le manuel de
> l'exploitant, *« Telegram deep scanner (module-telegram) »*.

## Les six outils

| Outil | Type de requête | Saisir la requête sous la forme… |
|------|-----------|---------------------|
| `telegram_scan` | `Canal Telegram` | `@canal`, un lien `t.me/…` ou `+inviteHash` (séparer plusieurs entrées par une virgule) |
| `telegram_channel_info` | `Canal Telegram` | `@canal` (séparer plusieurs entrées par une virgule) |
| `telegram_search` | `Recherche de canaux Telegram` | `@canal1,@canal2 :: mot-clé` |
| `telegram_user_lookup` | `Utilisateur Telegram / ID` | `@utilisateur` ou un ID numérique (séparer plusieurs entrées par une virgule) |
| `telegram_phone_lookup` | `Numéro de téléphone` | Numéros E.164, p. ex. `+41790000000` (séparer plusieurs entrées par une virgule) |
| `telegram_geo` | `Géo Telegram (lat,long)` | `47.3769,8.5417` |

Comme `telegram_scan` et `telegram_channel_info` répondent tous deux au type
de requête `Canal Telegram`, la sélection du module pour une requête de canal
exécute **les deux** — vous obtenez le scan complet *et* les métadonnées du
canal.

## Ce que renvoie chaque outil

**`telegram_scan`** — l'outil phare. Pour chaque canal/groupe/invitation :
- le **canal** (titre, description, nombre de membres, indicateur de vérification)
- les **messages** (texte, date, vues, transferts, réponses, réactions, géo)
- les **membres** et, sur demande, les **administrateurs** avec leurs rôles
- les messages **épinglés**
- les **médias** (nom de fichier, taille ; en option SHA-256 / hash perceptuel / EXIF)
- les **IOC** extraits du texte des messages (adresses crypto, e-mails, URL,
  numéros de téléphone, @mentions, #hashtags, liens `t.me/`)
- les **sources de transfert** sous forme de canaux liés

Il construit un graphe connecté : les messages *dans* le canal, les auteurs
qui les ont *publiés*, les membres *du* canal, les IOC *mentionnés*, les
médias *joints* et les transferts *provenant* d'autres canaux.

**`telegram_channel_info`** — métadonnées complètes du canal (description,
nombre de personnes en ligne, groupe de discussion lié, mode lent,
visibilité ou non des participants) ainsi que les **canaux similaires/
recommandés**.

**`telegram_search`** — recherche par mot-clé côté serveur dans les canaux
que vous indiquez. Syntaxe : les canaux à gauche de `::`, le mot-clé à
droite : `@ransomwatch,@leakchannel :: bitcoin`.

**`telegram_user_lookup`** — profil utilisateur complet : bio, statut en
ligne / dernière connexion, indicateurs bot/scam/fake/vérifié/premium, et
**discussions que vous avez en commun** avec la cible (par rapport au compte
de collecte).

**`telegram_phone_lookup`** — vérifie si un numéro de téléphone est présent
sur Telegram et, le cas échéant, résout le compte. Fortement limité en
fréquence — à utiliser pour des recherches individuelles, pas pour des listes
en masse. Les contacts importés sont automatiquement supprimés ensuite.

**`telegram_geo`** — trouve les utilisateurs/canaux proches d'une coordonnée
qui ont activé la visibilité géographique, avec la distance en mètres.

## Remarques opérationnelles

- **Un scan peut être volumineux.** Telegram plafonne les membres à ~10 000 ;
  le nombre de messages par canal suit la limite configurée par l'exploitant.
- **Les canaux privés / sur invitation uniquement** nécessitent `auto_join`
  (une option de l'exploitant) — sinon vous n'obtenez que les métadonnées,
  ce qui est clairement signalé.
- **Les paramètres de confidentialité** d'une cible peuvent masquer son
  téléphone, sa dernière connexion et ses photos de profil ; ces champs
  n'apparaissent alors tout simplement pas.
- **Preuves.** Chaque exécution Telegram est inscrite dans un journal d'audit
  inviolable, chaîné par hash (côté exploitant), qui consigne qui/quoi/quand
  de la collecte.
- **Protection des données (autorités de poursuite pénale suisses).** Le
  texte des messages et, si le hachage est activé, les médias sont collectés
  tels quels. Limitez les scans à ce dont le dossier a besoin.

---

Suite : **[Lire le graphe →](06-reading-the-graph.md)** · Retour : **[Modules & outils](04-modules-and-tools.md)**
