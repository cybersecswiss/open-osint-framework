# Modules & outils

Une **recherche** exécute un ou plusieurs **modules**. Chaque module regroupe
plusieurs **outils** qui interrogent de véritables sources OSINT. Vous
n'appelez jamais les outils directement — vous choisissez un **type de
requête**, saisissez un indicateur et cochez les modules souhaités. Le système
exécute automatiquement chaque outil qui comprend ce type de requête.

Il existe **14 modules** (environ 85 outils, dont trois désactivés par défaut). Certains outils nécessitent une clé API
configurée par votre exploitant ; sans elle, seul cet outil renvoie une
mention claire « clé non définie » au lieu de faire échouer la recherche.
Quelques modules sont optionnels (opt-in) et n'apparaissent que si votre
autorité dispose de la licence correspondante.

| # | Module | À quoi il sert | Clé nécessaire ? |
|---|--------|---------------|--------------|
| 1 | **Pivot d'alias** (`alias`) | Retrouver un nom d'utilisateur/alias sur le web | Non |
| 2 | **Fuites & violations** (`leaks`) | E-mail/nom d'utilisateur dans des fuites + empreinte de comptes | En partie |
| 3 | **Infrastructure** (`infra`) | Reconnaissance de domaine / IP, sosies d'hameçonnage | En partie |
| 4 | **Threat intel** (`threat`) | Réputation & attribution de maliciel d'un IOC | En partie |
| 5 | **Darknet & paste** (`darknet`) | Services cachés Tor, pastes, **veille des saisies** | Non |
| 6 | **Messagerie** (`messenger`) | Aperçu Telegram sans clé, Discord, téléphone→messagerie | En partie |
| 7 | **Traçage crypto** (`crypto`) | Adresses Bitcoin / Ethereum + attribution de portefeuilles | En partie |
| 8 | **Telegram (approfondi)** (`telegram`) | Collecte Telegram authentifiée et approfondie | Session |
| 9 | **Conformité & sanctions** (`compliance`) | Filtrage sanctions / PEP / listes de surveillance | En partie |
| 10 | **Forums criminels** (`forums`) | Recherche dans les forums, index d'acteurs de la menace, PGP, annuaires de liens | En partie |
| 11 | **OSINT Image** (`image`) | EXIF/GPS de photos + estimation IA du lieu | En partie |
| 12 | **Actualités & RSS** (`news`) | Recherche plein texte dans les flux des autorités, de la police, des médias et du domaine cyber | Non |
| 13 | **Entreprises & personnes** (`corporate`) | Registres, structure de groupe, listes de sanctions, annuaires — voir [sa propre page](15-companies-and-people.md) | Non |
| 14 | **Rencontre & adulte** (`dating`) | Recherche de pseudo sur les sites de rencontre/adultes — **désactivé par défaut** | Non |

---

## 1. Pivot d'alias — `alias`

Transforme un nom d'utilisateur ou un alias en une carte de comptes.

| Outil | Source | Remarques |
|------|--------|-------|
| `sherlock` | 600+ plateformes | Vérifie où un nom d'utilisateur existe |
| `whatsmyname` | Liste de sites tenue à jour en amont | Couverture des plateformes toujours actuelle |
| `user_scanner` | Multi-sites | Large balayage de présence d'un nom d'utilisateur |
| `linkook` | Graphe des comptes liés | Suit les liens entre les profils d'un utilisateur |

**Type de requête :** `Nom d'utilisateur / Alias`. Chaque résultat est
revérifié afin d'éliminer les faux positifs ; un compte listé existe donc
réellement.

## 2. Fuites & violations — `leaks`

Où une adresse e-mail/un nom d'utilisateur est apparu dans des fuites de
données, et auprès de quels services il est enregistré.

| Outil | Source | Clé |
|------|--------|-----|
| `holehe` | ~120 sites | Non — l'adresse y est-elle enregistrée ? |
| `hibp` | HaveIBeenPwned | Oui (`HIBP_API_KEY`) |
| `intelx` | Intelligence X | Non — produit un lien direct |
| `ghunt` | Compte Google | Session — e-mail/Gaia-ID → profil Google détaillé, avis Maps |
| `hudsonrock` | Renseignement infostealer | Sans clé — e-mail/domaine → infections par infostealer |

**Types de requête :** `E-mail` (+ `hudsonrock` aussi nom d'utilisateur/domaine,
`ghunt` aussi un Gaia ID).

> Les **mots de passe** ne sont stockés que sous forme d'empreinte SHA-256 +
> aperçu masqué (`a••••z`), sauf si votre exploitant active explicitement le
> stockage en clair.

## 3. Infrastructure — `infra`

Reconnaissance de domaines et d'adresses IP — et identification de
l'infrastructure d'**hameçonnage/de sosies** autour d'une marque.

| Outil | Source | Clé |
|------|--------|-----|
| `subfinder` | Énumération de sous-domaines | Non |
| `whois` | Enregistrement / titulaire | Non |
| `crtsh` | Journaux Certificate Transparency | Non |
| `dns_records` | A / AAAA / MX / NS / TXT / CNAME | Non |
| `theharvester` | E-mails/hôtes d'un domaine | Non |
| `shodan_host` | Ports ouverts, bannières, CVE | Oui (`SHODAN_API_KEY`) |
| `favicon_pivot` | Même favicon → hôtes apparentés | Oui (Shodan) |
| `dnstwist` | **Domaines de typosquatting / d'hameçonnage** | Non |
| `passive_dns` | Résolutions domaine↔IP **historiques** (Mnemonic) | Non |
| `asn_lookup` | Qui achemine cette adresse : préfixe, AS, titulaire (RIPEstat) | Non |
| `origin_resolve` | Serveur réel derrière un CDN (Cloudflare & co.), confirmé par interrogation directe — **désactivé par défaut** (`ENABLE_ORIGIN_RESOLVE`) | Non |

**Types de requête :** `Domaine`, `Adresse IP`, `URL`.
`dnstwist` transforme un domaine en liste de domaines sosies enregistrés
(homoglyphes/IDN, bitsquatting, changement de TLD …) qui se résolvent
effectivement — des candidats actifs d'hameçonnage/d'usurpation sur lesquels
pivoter.

**`passive_dns` est le seul qui regarde en arrière.** Tous les autres outils
ici répondent à « ce qui est vrai maintenant » — soit précisément l'état
qu'un opérateur modifie dès qu'il est grillé. Le DNS passif répond à « vers
quoi pointait ce domaine en mars dernier », dans les deux sens, et c'est
généralement là que se trouve le pivot. `asn_lookup` ajoute un nouveau nœud
`asn`, de sorte que les hôtes acheminés par le même réseau convergent dans le
graphe — le schéma typique de l'hébergeur « bulletproof ».

## 4. Threat intel — `threat`

Réputation, classification et **attribution de maliciel** d'un indicateur.

| Outil | Source | Clé |
|------|--------|-----|
| `virustotal` | VirusTotal | Oui |
| `abuseipdb` | AbuseIPDB | Oui |
| `urlhaus` | abuse.ch URLhaus | Sans clé/Clé |
| `greynoise` | GreyNoise community | Sans clé |
| `urlscan` | urlscan.io | Sans clé |
| `threatfox` | abuse.ch ThreatFox (IOC→maliciel) | Clé |
| `malwarebazaar` | abuse.ch MalwareBazaar (hash→échantillon) | Clé |
| `ransomware_watch` | Victimes des sites de fuite, groupes, leurs sites onion | Facultatif |
| `c2_intel` | Infrastructure de **commande et contrôle** connue, issue des scans Censys | Non |
| `ioc_reputation` | **Combien de listes de blocage indépendantes** contiennent cet indicateur | Non |
| `cve_lookup` | Détail de la CVE **ainsi que** le statut d'exploitation active (NVD + CISA KEV) | Non |

**Types de requête :** `Domaine`, `Adresse IP`, `URL`, `Hash`, `CVE`, `Mot-clé`.

Trois d'entre eux méritent d'être compris ensemble, car ils répondent à des
questions différentes sur la même adresse :

* `c2_intel` — *cet hôte a-t-il été vu en train de servir un panneau C2, et
  pour quelle famille de maliciels ?* Un résultat est une observation du
  logiciel lui-même, pas une opinion.
* `ioc_reputation` — *combien de listes de blocage indépendantes le
  répertorient ?* Une seule liste dit peu de chose ; la concordance entre des
  listes qui ne partagent pas de source en dit beaucoup. La réponse indique
  combien de listes ont été consultées, de sorte qu'un petit nombre se lit
  comme une indication de couverture plutôt que d'innocence.
* `cve_lookup` — *cette vulnérabilité est-elle réellement exploitée ?* Si le
  catalogue de la CISA est inaccessible, « exploitée » est signalé comme
  **inconnu**, jamais comme « non ».

`ransomware_watch` fonctionne sans clé, mais est alors limité à une requête
par minute et par point d'accès ; une clé gratuite de my.ransomware.live lève
cette limite, et l'outil la prend en compte de lui-même.

## 5. Darknet & paste — `darknet`

| Outil | Type de requête | Ce qu'il fait |
|------|-----------|--------------|
| `ahmia` | `Mot-clé` | Recherche en direct dans les services cachés Tor (Torch/TorDex) |
| `paste_search` | `Mot-clé` | Index de sites de paste |
| `seizure_watch` | `Domaine` (ou `.onion`) | **FBI-Watchdog :** détecte une **saisie/un démantèlement** par les autorités de poursuite pénale (bannière de saisie, noms d'agences) et fige l'infrastructure (enregistrements A/NS, redirection) afin qu'un changement puisse être repéré plus tard |
| `onion_scrape` | `Adresse onion` | Récupère un service caché via Tor et extrait ses contacts/IOC — **désactivé par défaut** (`ENABLE_ONION_SCRAPE`) |

## 6. Messagerie — `messenger`

Telegram + Discord sans clé, plus téléphone→messagerie.

| Outil | Type de requête | Ce qu'il fait |
|------|-----------|--------------|
| `telegram_channel` | `Canal Telegram` | Aperçu d'un canal public |
| `tgstat` | `Canal Telegram` | Statistiques/analytics du canal |
| `telegram_username_hunt` | `Nom d'utilisateur` | Parcourt les canaux criminels connus à la recherche de l'alias |
| `telegram_search` / `telegram_global_search` | `Recherche de canaux Telegram` | Moteurs de recherche Telegram publics |
| `telegram_message_search` | `Recherche de messages Telegram` | Mot-clé dans l'aperçu public |
| `discord_invite` | `Invitation Discord` | Résout une invitation → informations sur le serveur |
| `discord_snowflake` | `ID Discord (snowflake)` | Décode un ID utilisateur → **date de création du compte** (sans clé) |
| `discord_deep` | `ID Discord (snowflake)` | **Profil public complet** (nom, avatar/bannière, badges) — nécessite `DISCORD_BOT_TOKEN` |
| `phone_messenger` | `Numéro de téléphone` | Normalise un numéro (pays/opérateur/type de ligne) + un **lien direct WhatsApp** à vérifier manuellement |

> `phone_messenger` n'affirme jamais qu'un numéro « est sur WhatsApp » — il
> n'existe pas de vérification automatisée conforme. Il vous fournit les
> détails vérifiés du numéro et un lien que vous ouvrez vous-même.

## 7. Traçage crypto — `crypto`

| Outil | Source | Clé |
|------|--------|-----|
| `blockchain_btc` | blockchain.info | Sans clé |
| `etherscan_eth` | Etherscan | Oui (`ETHERSCAN_API_KEY`) |
| `blockscout` | Blockscout (solution de repli ETH sans clé) | Sans clé |
| `wallet_attribution` | MistTrack | Oui — portefeuille → cluster plateforme d'échange/mixeur/escroquerie/rançongiciel + risque |

**Types de requête :** `Adresse Bitcoin`, `Adresse Ethereum`.

## 8. Telegram (approfondi) — `telegram`

Collecte MTProto authentifiée — historique complet, membres et recherches
utilisateur/téléphone/géo. Nécessite une **session** Telegram mise en place
par votre exploitant. Page dédiée : **[Outils Telegram](05-telegram.md)**.

## 9. Conformité & sanctions — `compliance`

| Outil | Source | Clé |
|------|--------|-----|
| `opensanctions` | OpenSanctions (OFAC/UE/ONU/SECO…) | Oui, ou auto-hébergement sans clé |

Contrôle un **nom, une entreprise ou un portefeuille crypto** par rapport aux
listes de sanctions / PEP / listes de surveillance. **Types de requête :**
`Mot-clé`/nom, adresse crypto.

## 10. Forums criminels — `forums`

| Outil | Ce qu'il fait | Clé |
|------|--------------|-----|
| `crime_forum_hunt` | Interroge par dorks les forums criminels du clearnet et du darknet pour un terme/alias/ID de contact | Une clé Brave aide |
| `threat_actor_check` | Recherche un alias dans un vaste index d'acteurs de la menace | Sans clé |
| `linkbase_lookup` | Recherche dans un annuaire de liens darknet organisé | Sans clé |
| `pgp_lookup` | Trouve/analyse la clé PGP d'un acteur + son empreinte | Sans clé |

**Types de requête :** `Mot-clé`, `Nom d'utilisateur`, ainsi que des ID de
contact (`Jabber`, `Tox`, `Session`, empreinte PGP).

## 11. OSINT Image — `image`

Extraire des indices de localisation d'une photo. **Type de requête :**
`URL d'image`.

| Outil | Ce qu'il fait | Clé |
|------|--------------|-----|
| `exif_gps` | Lit les données EXIF intégrées : marque/modèle de l'appareil, horodatage et **GPS** → un nœud `location` avec le nom du lieu | Non |
| `visual_geolocate` | En l'absence de GPS, une **IA estime le lieu** à partir d'indices visibles (panneaux, architecture) — clairement signalé comme *estimation IA*, une piste à vérifier | Oui (Gemini) |

> L'estimation IA est une piste, pas une preuve. Si le modèle ne peut pas
> trancher, il le dit et n'ajoute rien — il n'invente jamais de lieu.

## 12. Actualités & RSS — `news`

| Outil | Type de requête | Ce qu'il fait |
|------|-----------|--------------|
| `news_search` | `Mot-clé` | Recherche plein texte dans les flux gérés par votre exploitant — organes fédéraux, police, médias, technologie et cyber |

Chaque résultat comporte **la date, la source et le type de source**. Un
communiqué d'une autorité et un article de journal sont tous deux des pistes
légitimes, mais n'ont pas la même valeur probante ; c'est pourquoi les
sources officielles reçoivent aussi un niveau de confiance plus élevé. Voir
[Effectuer une recherche](03-searching.md#news--rss).

---

Suite : **[Outils Telegram →](05-telegram.md)** · Retour : **[Recherche](03-searching.md)**

## 14. Rencontre & adulte — `dating`

**Désactivé par défaut.** L'opérateur l'active délibérément avec
`ENABLE_DATING_SEARCH=true` ; jusque-là le module ne propose aucun outil.
Prévu pour des pistes concrètes : sextorsion, arnaque sentimentale, traite.

> ⚠️ Avoir un profil sur une plateforme de rencontre ou pour adultes est une
> information sur la vie sexuelle d'une personne — une donnée sensible.
> N'effectuez cette recherche qu'avec une base légale et un but précis, et
> traitez ces dossiers de manière restreinte.

| Outil | Type de requête | Ce qu'il fait |
|-------|-----------------|---------------|
| `cupidcrawl` | `Nom d'utilisateur` | Parcourt ~50 plateformes de rencontre/adultes ; chaque résultat est vérifié par un contrôle négatif |

