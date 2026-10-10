# Suivi GitHub automatique (issues + board)

Steering toujours inclus. Tout le monde code avec Kiro : **c'est l'assistant qui doit effectuer
ces gestes de suivi lui-même**, sans attendre que l'utilisateur les demande ni qu'il lise la
sortie. Faire ces actions au bon moment, puis dire en une ligne ce qui a été fait.

## Prérequis (sinon ces commandes échouent)

- `gh` (GitHub CLI) installé et authentifié : `gh auth status` doit être vert.
  Sous Windows, le binaire est `"$env:ProgramFiles\GitHub CLI\gh.exe"` s'il n'est pas dans le PATH.
- Si `gh` n'est pas authentifié, NE PAS inventer de token : le signaler à l'utilisateur et
  continuer le travail de code sans bloquer.

## Constantes du projet

- Dépôt : `marceaupatu123/secure-horizons`
- Board : Project **n°5** (`--owner marceaupatu123`), URL
  <https://github.com/users/marceaupatu123/projects/5>
- Labels : `module:<nom>` (dossier), `wave:0..5` (ordre, voir `docs/ROADMAP.md`).

## Gestes à effectuer automatiquement

### 1. Quand on COMMENCE à travailler sur une tâche

- S'assigner l'issue correspondante et la passer visible comme en cours :

  ```bash
  gh issue edit <N> --add-assignee "@me"
  ```

- Déplacer la carte du board en **In Progress** (le board se met aussi à jour tout seul quand une
  PR est liée, mais le faire des le debut est plus clair). Statut via l'UI, ou laisser le workflow
  natif « Pull request linked to issue » s'en charger a l'ouverture de la PR.

### 2. Quand on OUVRE une Pull Request

- Toujours inclure **`Closes #<N>`** dans la description : au merge, GitHub ferme l'issue ET passe
  la carte du board en **Done** automatiquement (workflows natifs du Project déjà actifs).

  ```bash
  gh pr create --fill        # puis s'assurer que la description contient "Closes #<N>"
  ```

- Nommer la branche avec le numéro d'issue aide le suivi : `feat/<N>-<courte-description>`.

### 3. Quand on DÉCOUVRE une tâche manquante / crée du travail nouveau

- Créer une issue correctement étiquetée ET l'ajouter au board :

  ```bash
  gh issue create --title "<module>: <titre>" --label "module:<x>,wave:<n>" --body "<...>"
  gh project item-add 5 --owner marceaupatu123 \
    --url https://github.com/marceaupatu123/secure-horizons/issues/<N nouveau>
  ```

### 4. Quand la tâche est TERMINÉE

- Vérifier que l'issue se fermera bien via la PR (`Closes #N`). Sinon fermer manuellement :
  `gh issue close <N>`.
- Cocher la ligne correspondante dans `docs/ROADMAP.md`.

## Ce qui est déjà automatique côté GitHub (ne pas refaire à la main)

- Issue/PR fermée → carte du board en **Done**.
- PR mergée → carte en **Done**.
- `main` est protégée : PR obligatoire + CI vert requis. Ne jamais tenter de push direct sur
  `main` ; travailler sur une branche et ouvrir une PR.

## Limite

Ces gestes relèvent du steering : les faire au mieux, mais si une commande `gh` échoue (auth,
réseau), le signaler brièvement et poursuivre le travail de code — ne jamais bloquer la tâche
principale pour un problème de suivi.
