# Rapports

Vous pouvez transformer n'importe quel dossier en **rapport PDF** — utile
pour le dossier officiel, pour la communication au Ministère public ou à la
défense, ou pour informer des collègues.

## Générer un rapport

1. Ouvrez le dossier et cliquez sur **« Rapport PDF »** dans l'en-tête
   (cela ouvre la page **« Générer un rapport PDF »**).
2. Sous **« Sections à inclure »**, cochez les parties souhaitées. Sections
   disponibles, dans l'ordre où elles apparaissent dans le document :
   - **« Page de couverture »** — logo, numéro de dossier, titre, statut
   - **Résumé** — ce que contient le dossier, ventilé par type
   - **Conclusions clés** — les vingt résultats les mieux classés *avec la
     raison de leur classement* : quels outils les ont confirmés et comment
     la source est cotée. C'est la section à donner au lecteur qui n'en lira
     qu'une seule.
   - **Tableau des entités** — tous les résultats, triés par pertinence
     plutôt que par ordre alphabétique
   - **Relations** — qui est lié à qui, groupé par type, **avec l'outil qui
     a établi chaque lien**
   - **Image du graphe** — une image du réseau, où des doubles anneaux
     signalent les résultats rapportés par plus d'un outil
   - **Recherches** — quelles recherches ont produit ce dossier
   - **Alertes**
   - **Chronologie**
   - **Sources** — l'annexe des citations : URL de la source, outil, et date
     à laquelle la source l'a affirmé par rapport à la date d'enregistrement

   Toutes sont présélectionnées par défaut ; décochez ce dont vous n'avez
   pas besoin.

> **Le rapport indique ce qu'il a laissé de côté.** Si des éléments du
> dossier sont marqués comme pertinents, le rapport contient exactement ces
> résultats ; sinon, il contient tout ce qui n'est pas marqué comme faux
> positif. Dans les deux cas, il indique quelle règle s'est appliquée et
> combien d'éléments ont été écartés — un rapport filtré qui ne dit pas
> qu'il est filtré serait pire qu'un rapport non filtré. Les espaces
> réservés ne sont jamais comptés comme résultats (voir [Évaluer les
> résultats](12-assessing-findings.md)).
3. Le rapport est rendu dans **la langue actuelle de votre interface**
   (*« Le rapport sera rendu en {langue}… »*) — changez d'abord la langue
   avec le sélecteur de l'en-tête si vous en souhaitez une autre.
4. Cliquez sur **« Générer le PDF »**. Le fichier est téléchargé sous le
   nom `{case_number}.pdf` et le message **« Rapport téléchargé »**
   s'affiche.

En cas d'échec, vous verrez *« Échec de la génération du rapport »* —
réessayez ou réduisez les sections sélectionnées, et informez votre
exploitant si le problème persiste.

## Conseils

- **Marquez les entités clés comme pertinentes** avant de générer le
  rapport — les entités signalées ressortent dans le rapport.
- La **page de couverture** utilise le **logo** et le nom d'affichage de
  votre organisation, qu'un admin définit sous **Admin → Paramètres**.
- Générez un nouveau rapport chaque fois que le dossier a évolué ; le PDF
  est un instantané à un moment donné, pas un document vivant.

## Options du rapport

- **Uniquement les résultats marqués comme pertinents (extrait)** — tableaux,
  graphe et pages sauvegardées ne montrent que les résultats marqués ★ et les
  liens entre eux. Chaque page porte la mention *« Extrait »*. Sans la case,
  le rapport contient tous les résultats sauf ceux marqués comme faux positifs.
- **PDF ou Word** — Word sert à retravailler le texte : même contenu et mêmes
  images, mise en page plus simple.
- Deux sections supplémentaires : **« Journal des recherches »** (qui a
  recherché quoi, quand et dans quel but) et **« Pages sauvegardées »**
  (captures avec SHA-256, pour qu'un lecteur puisse vérifier un fichier).
- Un dossier créé avec un **modèle** démarre avec la structure de son type
  d'infraction.

---

Suite : **[Référence & glossaire →](09-reference.md)** · Retour : **[Surveillance & alertes](07-monitoring-and-alerts.md)**
