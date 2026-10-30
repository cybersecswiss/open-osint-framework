# Référence et glossaire

## Types de requête

Le **type de requête** indique à la plateforme comment interpréter votre
terme de recherche et quels modules/outils peuvent le traiter. Choisissez-le
dans la liste déroulante *Type* du formulaire de recherche.

| Type de requête (liste déroulante) | Exemple de saisie | Traité en général par |
|-----------------------|---------------|----------------------|
| Nom d'utilisateur / Alias | `anonymous99` | alias, leaks (hudsonrock), messenger (recherche de nom d'utilisateur) |
| E-mail | `max@example.com` | leaks |
| Domaine | `example.com` | infra, threat |
| Adresse IP | `1.2.3.4` | infra, threat |
| URL | `http://bad.example/x` | threat |
| Hash (MD5/SHA1/SHA256) | `sha256:…` | threat |
| Numéro de téléphone | `+41790000000` | **telegram** |
| Adresse Bitcoin | `bc1q…` | crypto |
| Adresse Ethereum | `0x…` | crypto |
| Canal Telegram | `@durov` | messenger (sans clé), **telegram** (approfondi) |
| Recherche de canaux Telegram | `ransomware` | messenger |
| Recherche de messages Telegram | `@chan :: keyword` | messenger |
| Utilisateur Telegram / ID | `@user` | **telegram** |
| Géo Telegram (lat,long) | `47.3769,8.5417` | **telegram** |
| Invitation Discord | `discord.gg/abc` | messenger |
| Mot-clé (forums/darknet/paste) | `acme breach` | darknet |

Seuls les modules qui comprennent le type de requête choisi apparaissent
comme options à cocher dans le formulaire de recherche.

## Types d'entités dans le graphe

Les nœuds sont colorés selon leur type. Les types inconnus s'affichent en
gris et fonctionnent quand même.

| Couleur | Type d'entité | Signification |
|:------:|-------------|---------|
| 🔵 | `person` | Une personne |
| 🟢 | `social_account` | Un compte de réseau social |
| 🟠 | `organization` | Une organisation |
| 🔴 | `email_address` | Une adresse e-mail |
| 🟣 | `domain` | Un domaine |
| 🩵 | `username` | Un nom d'utilisateur / alias |
| 🩷 | `ip_address` | Une adresse IP |
| 🟢 | `phone_number` | Un numéro de téléphone |
| 🟧 | `location` | Un lieu géographique |
| 🔵 | `telegram_channel` | Un canal/groupe Telegram |
| 🔵 | `telegram_message` | Un message Telegram |
| 🔵 | `telegram_user` | Un utilisateur Telegram |
| 🔵 | `telegram_media` | Un fichier média dans Telegram |
| 🔴 | `telegram_ioc` | Un indicateur (crypto/e-mail/URL/…) trouvé dans un message |
| 🟣 | `telegram_linked_channel` | Un canal référencé via un transfert |

## Relations des arêtes

Les arêtes portent le libellé de la relation. La collecte Telegram produit :

`POSTED` · `POSTED_IN` · `IN_CHANNEL` · `MEMBER_OF` · `ADMIN_OF` ·
`PINNED_IN` · `REPLY_TO` · `FORWARDED_FROM` · `MENTIONS` · `HAS_MEDIA` ·
`COMMON_CHAT` · `LINKED_DISCUSSION` · `SIMILAR_TO`

D'autres modules ajoutent les leurs (p. ex. un lien alias-vers-compte).
Survolez une arête dans le graphe pour voir son libellé.

## Types d'indicateurs (IOC) extraits du texte Telegram

`btc` · `eth` · `xmr` · `ltc` · `tron` (adresses crypto) · `email` ·
`url` · `telegram_link` · `phone` · `mention` (@handle) · `hashtag`.

## Glossaire

- **Dossier** — le conteneur d'une enquête. Chaque résultat de recherche
  est rattaché à un dossier.
- **Entité** — un nœud dans le graphe du dossier (une personne, un compte,
  un canal, une adresse, un message, …).
- **Arête** — une relation étiquetée entre deux entités.
- **Module** — un collecteur autonome (l'un des 8). Vous choisissez ceux à
  exécuter pour chaque recherche.
- **Outil** — une source individuelle au sein d'un module (p. ex.
  `virustotal`).
- **Type de requête** — la manière dont votre terme de recherche est
  interprété (voir ci-dessus).
- **IOC** — Indicator of Compromise (indicateur de compromission) : une
  adresse crypto, un e-mail, une URL, un hash, etc.
- **Locataire** — votre organisation. Vos données résident dans le stockage
  de votre propre organisation ; l'exploitant de la plateforme ne peut pas
  les lire.
- **Session (Telegram)** — la connexion Telegram authentifiée qu'utilise le
  module approfondi ; elle est entretenue par votre exploitant.

## Dépannage

| Symptôme | Signification / que faire |
|---------|----------------------|
| Une ligne d'outil affiche une remarque « key not set » | Cette source nécessite une clé API que votre exploitant n'a pas configurée. Les autres outils ont tout de même été exécutés. |
| Les outils Telegram indiquent « not authenticated » | La session Telegram est inactive — demandez à votre exploitant de la réauthentifier. |
| Aucun module n'apparaît pour mon type de requête | Aucun module installé ne traite ce type ; choisissez un autre type ou un autre terme. |
| Un nœud semble isolé | Il s'agit du terme que vous avez recherché (la « racine », *root*), ou d'une extrémité pour laquelle aucun outil n'a renvoyé de détails complets. |
| La recherche est terminée mais il y a peu de résultats | Normal — un résultat négatif net (comme un e-mail sans fuite de données) est un résultat valable. |

## Paramètres de l'autorité (pour les administrateurs)

Sous **Admin → Paramètres**, l'administration de votre autorité définit pour
tous :

| Paramètre | Effet |
|---|---|
| Nom affiché, logo | En-tête et page de couverture des rapports |
| Langue par défaut | Langue de l'interface tant qu'un utilisateur n'en a pas choisi une |
| Exiger une finalité pour chaque recherche | Recherches et nouvelles surveillances exigent une finalité / base légale, consignée dans le journal des recherches |
| Mention de classification dans le rapport | En rouge sur chaque page de chaque rapport PDF |
| Playbook par défaut | Présélectionné dans la recherche lorsqu'il convient |
| Modules désactivés | Modules sous licence que votre autorité n'utilise pas — retirés de la recherche et des surveillances existantes |
| Délai de session, suppression automatique | Déconnexion après inactivité ; suppression des dossiers clos après N mois |

Les modules ne peuvent qu'être **désactivés** ici ; les modules sous licence
relèvent de votre contrat avec l'exploitant de la plateforme.

**Autotest.** *Admin → Autotest* vérifie, dans une liste avec feux de
signalisation, si votre installation fonctionne : licence, stockage (joignable,
clé acceptée, à jour), certificat TLS, intégrité de la chaîne du journal,
service de connexion, canal d'alerte et sauvegarde de preuves — chacun avec une
phrase indiquant quoi faire. À lancer après chaque installation ou mise à jour.

---

Retour : **[Accueil](00-overview.md)**
