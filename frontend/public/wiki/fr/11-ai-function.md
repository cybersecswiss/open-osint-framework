# La fonction IA (liaison assistée)

La **fonction IA** est une aide optionnelle, soumise à licence, qui examine
le graphe d'un dossier et **suggère** comment les éléments pourraient être
liés — des grappes d'identité (« ces comptes semblent appartenir à la même
personne »), des relations probables entre nœuds, ainsi qu'une brève
évaluation avec des étapes suivantes.

Elle est **assistante, jamais automatique**. L'IA ne fait que proposer ;
c'est *vous* qui décidez de ce qui est avéré et qui validez les liens avec
lesquels vous êtes d'accord. Rien n'est ajouté au dossier à votre insu.

> **Disponibilité.** Le bouton n'apparaît que si votre autorité dispose d'une
> **licence** pour la fonction IA. Si vous ne le voyez pas, la fonction n'est
> pas activée pour votre compte — c'est normal.

## Utilisation

1. Ouvrez un dossier contenant quelques résultats et allez dans le
   **Graphe réseau** (ou dans le panneau IA du dossier).
2. Cliquez sur **« Liaison IA »**. Une tâche démarre et s'exécute en
   arrière-plan — vous pouvez continuer à travailler ; la page n'est pas
   bloquée.
3. Une fois la tâche terminée, vous obtenez des **suggestions** :
   - **Grappes d'identité** — des groupes de nœuds que le modèle considère
     comme le même acteur.
   - **Liens suggérés** — des arêtes proposées entre nœuds, chacune avec une
     brève justification.
   - Une courte **évaluation** et des **étapes suivantes** à envisager.
4. **Examinez chaque suggestion.** Appliquez celles avec lesquelles vous
   êtes d'accord (elles deviennent de véritables arêtes dans le graphe,
   marquées `source: ai`) ; ignorez les autres. Réappliquer plus tard la
   même suggestion est sans conséquence — elle ne sera pas dupliquée.

## Ce que l'IA voit (et ne voit pas)

Afin de garder autant que possible les données du dossier à l'intérieur de
votre périmètre souverain, la plateforme n'envoie au modèle que la
**structure du graphe** — types de nœuds, étiquettes et indications
condensées — et **supprime les valeurs sensibles** avant tout envoi (les mots
de passe, cookies, jetons, hash, bannières brutes et identifiants en clair ne
sont jamais transmis). Les gros blocs de données sont réduits à de courts
résumés ; les identifiants enfouis (un e-mail, un numéro de téléphone ou un
pseudo isolé) sont conservés, car ce sont précisément eux qui aident à
établir les liens.

> **Remarque sur la souveraineté.** Avec le modèle cloud par défaut
> (Gemini), le graphe épuré quitte bel et bien votre infrastructure pour
> être transmis au fournisseur. C'est pourquoi la fonction est **soumise à
> licence par autorité et utilisée avec consentement**. Un modèle
> entièrement local constitue l'alternative souveraine prévue dans la feuille
> de route.

## Bonnes pratiques

- **Traitez les suggestions comme des pistes, pas comme des verdicts.**
  Vérifiez un lien proposé au regard des preuves sous-jacentes avant de vous
  y fier dans un rapport.
- **Commencez par cibler le dossier.** Marquer les nœuds manifestement
  pertinents et retirer les faux positifs avant de lancer l'IA lui fournit
  des données plus propres et de meilleures suggestions.
- **Grands dossiers :** seuls les résultats les plus pertinents (un nombre
  plafonné, fixé par votre exploitant) sont analysés — la remarque d'analyse
  vous indique combien ont été utilisés, et sur combien.

## Si elle ne s'exécute pas

- **« not licensed »** (pas de licence) — la fonction IA n'est pas activée
  pour votre autorité.
- **« quota / rate-limit reached »** (quota / limite de débit atteint) — la
  limite d'utilisation du fournisseur a été atteinte ; votre exploitant doit
  la relever (activer la facturation) ou attendre sa réinitialisation.
- **« took too long »** (trop long) — un très grand dossier ; votre
  exploitant peut abaisser le plafond d'entités, ou vous pouvez cibler le
  dossier et réessayer.

Ces cas sont signalés par un message clair sur la tâche, et non par un échec
silencieux.

---

Suite : **[Surveillance et alertes →](07-monitoring-and-alerts.md)** · Retour : **[Lire le graphe](06-reading-the-graph.md)**
