# AI_WORKFLOW.md — comment bosser avec l'IA sans marcher sur les pieds des autres

Ce guide s'adresse à toute l'équipe 20. On est 4–5 à coder en parallèle, chacun avec son propre
assistant IA (Kiro, Claude, Copilot...). La règle d'or : **un dossier = un propriétaire**. Ce
document explique comment parler à ton assistant pour rester dans ton périmètre.

---

## TL;DR (à lire absolument)

1. **Tu ne touches qu'à TON dossier.** Celui qui t'est assigné dans `docs/TEAM.md`.
2. **Tu ne modifies JAMAIS `shared/` ni `docs/CONTRACTS.md`** sans accord explicite de l'équipe.
   Ce sont nos interfaces communes : si quelqu'un les change seul, tout le monde casse.
3. **Avant de coder, dis à ton IA sur quel dossier tu travailles** (voir le modèle de prompt).
4. **Rien n'est décidé par l'IA.** Les choix d'archi/seuils/design vont dans
   `docs/OPEN_QUESTIONS.md`, on tranche en équipe. Une fois tranchée, la réponse est copiée
   dans `docs/OPEN_ANSWERS.md` (avec un renvoi depuis la question).
5. **Branche + commit + push + PR au moins toutes les heures.** GitHub est notre seule sauvegarde
   (le compte AWS est supprimé à la fin).

---

## Qui possède quoi

La répartition officielle est dans **`docs/TEAM.md`** (tableau module → propriétaire → branche).
Avant de commencer, vérifie :

- Quel dossier est le tien.
- Quelle branche tu utilises (format conseillé : `prenom/module`).

Si tu as besoin de modifier le dossier de quelqu'un d'autre : **préviens-le d'abord** (oral/chat),
et faites-le ensemble ou via une PR qu'il relit.

### Zones partagées — accord explicite obligatoire

| Zone | Pourquoi c'est sensible | Règle |
|------|-------------------------|-------|
| `shared/` | Modèles de données communs (Pydantic) utilisés par tous. | On n'y touche pas seul. |
| `docs/CONTRACTS.md` | Les interfaces entre modules. Changer un champ casse les autres. | On n'y touche pas seul. |
| `requirements.txt` | Source unique des dépendances. | Ajout = prévenir l'équipe. |
| `Makefile`, `.githooks/`, `.env.example`, `.gitignore` | Outillage commun. | On n'y touche pas sans raison partagée. |

---

## Le réflexe : cadrer ton IA au début de CHAQUE session

Les assistants IA ne connaissent pas nos règles d'équipe par défaut (sauf Kiro, qui lit le
steering `.kiro/steering/collaboration.md`). Commence toujours par leur donner ton périmètre.

### Modèle de prompt d'ouverture (copie-colle, adapte le dossier)

```
Contexte : projet d'équipe "secure-horizons" (hackathon). Je suis responsable UNIQUEMENT du
dossier `<TON_MODULE>/`. Règles à respecter absolument :
- Tu ne modifies QUE les fichiers sous `<TON_MODULE>/`.
- Tu ne touches JAMAIS à `shared/` ni à `docs/CONTRACTS.md`.
- Si une interface entre modules est nécessaire, tu NE la définis pas toi-même : tu me poses la
  question et je l'apporte à l'équipe (elle vivra dans docs/CONTRACTS.md et shared/).
- Toute décision d'archi / de seuils / de design n'est PAS tranchée par toi : propose des options
  et je les note dans docs/OPEN_QUESTIONS.md.
- Avant d'écrire du code, lis d'abord CLAUDE.md et docs/TEAM.md.
Confirme que tu as compris le périmètre avant de commencer.
```

> Avec **Kiro**, ces règles sont déjà chargées via `.kiro/steering/collaboration.md`, mais répéter
> ton dossier au début reste une bonne habitude.

### Phrases utiles pendant la session

- « Reste dans `<TON_MODULE>/`, ne modifie aucun autre dossier. »
- « Tu veux changer un modèle partagé : stop. Explique-moi pourquoi, je verrai avec l'équipe. »
- « C'est une décision de conception : ne tranche pas, propose 2–3 options et je les note dans
  `OPEN_QUESTIONS.md`. »
- « Ajoute d'abord cette dépendance à `requirements.txt` et rappelle-moi de prévenir l'équipe. »

### Signaux d'alarme — reprends la main si ton IA :

- veut éditer un fichier **hors de ton dossier** ;
- modifie un champ dans `shared/` ou `docs/CONTRACTS.md` « pour que ça marche » ;
- ajoute une **dépendance** sans te le dire ;
- **invente des chiffres** (perte max, taux de faux positifs) : on n'affiche que ce qu'on a mesuré
  (voir `docs/CLAIMS.md`) ;
- écrit « prouvé » ou « révolutionnaire » : au mieux « vérifié par tests ».

---

## Workflow git pour chacun (toutes les heures)

```bash
# 1. Partir à jour depuis main
git checkout main
git pull

# 2. Travailler sur SA branche
git checkout -b prenom/mon-module      # ou: git checkout prenom/mon-module

# 3. Petits commits (le hook anti-secrets tourne automatiquement si make install a été lancé)
git add <tes fichiers du module>       # évite git add -A si tu touches à plein de choses
git commit -m "feat(mon-module): ..."

# 4. Pousser + ouvrir une PR (au moins toutes les heures)
git push -u origin prenom/mon-module
# puis ouvrir la PR sur GitHub (gabarit pré-rempli : .github/pull_request_template.md)
```

Conseils :

- **Préfère `git add <fichier>`** à `git add -A` : tu évites d'embarquer le dossier d'un autre.
- **Une PR = un module** autant que possible. Coche les modules touchés dans le gabarit de PR.
- Si tu dois absolument toucher à `shared/` ou `docs/CONTRACTS.md`, **dis-le dans la PR** et fais
  relire par l'équipe.

## Tests obligatoires sur chaque PR (CI)

Un workflow GitHub Actions (`.github/workflows/ci.yml`) tourne **automatiquement sur chaque PR** :
il installe les dépendances, lance le lint (`compileall`) et les tests (`pytest`). **Une PR dont
le CI est rouge ne se fusionne pas.**

Règle d'équipe : **chaque nouvelle fonction arrive avec ses tests.** Concrètement, quand tu
ajoutes une fonction dans ton module, ajoute un test dans `ton_module/tests/` (à côté du
`test_smoke.py` existant). Un test ciblé suffit : appeler la fonction et vérifier le résultat
attendu (ou qu'elle lève bien l'erreur prévue).

Phrase utile pour ton IA :

> « À chaque fonction que tu écris dans `<TON_MODULE>/`, ajoute un test correspondant dans
> `<TON_MODULE>/tests/`. Lance `pytest` et montre-moi qu'il passe avant qu'on commite. »

Vérifie en local avant de pousser :

```bash
make test        # ou : python -m pytest -q
```

---

## Comment on fait évoluer une interface commune (le cas délicat)

Tu as besoin d'un nouveau champ dans un modèle partagé (ex : `Alert`) ? **Ne le fais pas seul.**

1. Note le besoin dans `docs/OPEN_QUESTIONS.md` (ou dis-le dans le canal d'équipe).
2. On se met d'accord sur le champ (nom, type) à l'oral ou en PR.
3. **Une seule personne** (le propriétaire de `shared/`) met à jour `shared/` + `docs/CONTRACTS.md`
   dans une PR dédiée.
4. Les autres récupèrent (`git pull`) avant de continuer.

Comme ça, personne ne découvre un modèle changé sous ses pieds.

---

## Où est quoi (rappel)

| Fichier | À quoi ça sert pour toi |
|---------|-------------------------|
| `docs/TEAM.md` | Qui possède quel module + ta branche. |
| `CLAUDE.md` | But du projet + conventions + règles de collab (contexte à donner à l'IA). |
| `.kiro/steering/collaboration.md` | Mêmes règles, chargées automatiquement par Kiro. |
| `docs/CONTRACTS.md` | Les interfaces entre modules (zone partagée, lecture OK, écriture = accord). |
| `docs/OPEN_QUESTIONS.md` | Toutes les décisions non tranchées : on y dépose, on n'invente pas. |
| `docs/OPEN_ANSWERS.md` | Toutes les décisions tranchées (copie, avec date, auteur et ce qui reste ouvert). |
| `docs/CLAIMS.md` | Ce qu'on dira au jury + comment on le vérifie (aucun chiffre sans mesure). |
| `.github/pull_request_template.md` | Le gabarit à remplir pour chaque PR. |

En cas de doute : demande dans le canal d'équipe **avant** de laisser l'IA modifier quoi que ce
soit hors de ton dossier.

---

## Fonctionnalités Kiro à utiliser (dans l'IDE)

Kiro embarque des fonctions natives (panneau de gauche) déjà configurées **dans le repo** : au
clone, tu en hérites sans rien installer.

### Steering — règles chargées automatiquement

Les fichiers de `.kiro/steering/` injectent des règles dans ton assistant Kiro sans que tu aies à
les répéter :

- **`collaboration.md`** — règles d'équipe + but du projet, **toujours** chargé.
- **`module-<nom>.md`** (monitor, detection, llm, response, dashboard, shared, contracts) —
  chargés **automatiquement** quand tu ouvres/édites un fichier du dossier correspondant. Ils
  rappellent à l'IA ton périmètre, les décisions non tranchées et l'obligation de tests.

Concrètement : si tu bosses dans `detection/`, Kiro charge tout seul `module-detection.md` et sait
qu'il ne doit pas toucher `shared/`. **Tu n'as rien à activer.**

> Les steering en section **Global** (chez un membre) sont personnels à sa machine et ne sont PAS
> partagés. Seuls ceux de `.kiro/steering/` (section Workspace) sont dans le repo.

### Agent Hooks — automatisations partagées

Dans `.kiro/hooks/` (partagé via le repo) :

- **`pytest-on-save`** — lance `pytest` à chaque sauvegarde d'un fichier `.py`. Filet de sécurité
  local : tu vois tout de suite si tu casses un test, avant même de pousser. Actif au prochain
  démarrage de session Kiro après le clone.

Tu peux en créer d'autres via **Agent Hooks › Create New Hook** (ou la palette : « Open Kiro Hook
UI »). Garde-les simples et utiles à toute l'équipe.

### Specs — pour les tâches un peu grosses

Pour un morceau conséquent (contrat protégé, orchestration de réponse), lance une **Spec**
(panneau Specs › Create New Spec) : elle cadre requirements → design → tâches avant de coder.
C'est individuel, rien à partager.

### MCP Servers — connecter des outils externes (optionnel)

Via `.kiro/settings/mcp.json` (workspace) ou `~/.kiro/settings/mcp.json` (perso). Utile ici :

- **AWS Documentation MCP** — pratique pour le module `llm` (Bedrock, API Converse).

À n'activer que si le besoin se présente ; non indispensable pour 48 h.

### Ce que chaque membre fait après le clone

1. Ouvrir le projet dans Kiro → le steering `collaboration` + les `module-*` s'activent seuls.
2. Lancer `make install` (deps + hook anti-secrets git).
3. Coder dans SON dossier : le hook `pytest-on-save` tourne à chaque sauvegarde.
4. Rien d'autre à installer côté Kiro : tout est versionné dans `.kiro/`.

---

## Tenir les issues et le board à jour (NE PAS OUBLIER)

Le suivi ne vaut que s'il reflète la réalité. **À chaque fois que tu commences, avances ou
termines une tâche, mets l'issue et le board à jour.** Dis-le aussi explicitement à ton assistant
IA — il ne le fera pas tout seul si tu ne le demandes pas.

Références :
- Issues : <https://github.com/marceaupatu123/secure-horizons/issues>
- Board (Project n°5) : <https://github.com/users/marceaupatu123/projects/5>
- Ordre de travail : `docs/ROADMAP.md` (vagues `wave:0` → `wave:5`).

### Le réflexe à chaque étape

| Moment | Action |
|--------|--------|
| Je prends une tâche | M'assigner l'issue + la passer en **In Progress** sur le board. |
| J'ouvre une PR | Référencer l'issue dans la PR (`Closes #N`) pour la fermer automatiquement au merge. |
| Je finis / la PR est mergée | Vérifier que l'issue est **close** et la carte en **Done**. |
| Je découvre une tâche manquante | Créer une **nouvelle issue** (avec label `module:*` + `wave:*`) et l'ajouter au board. |
| Je coche une case dans `ROADMAP.md` | Le faire aussi quand la tâche est réellement terminée. |

### Commandes `gh` utiles

```bash
# Voir ce qu'il y a à faire maintenant
gh issue list --label "wave:0"
gh issue list --label "module:detection"

# Prendre une issue : se l'assigner
gh issue edit <N> --add-assignee "@me"

# Ouvrir une PR qui ferme l'issue au merge
gh pr create --fill            # puis écrire "Closes #<N>" dans la description

# Fermer / rouvrir manuellement si besoin
gh issue close <N>
gh issue reopen <N>

# Créer une nouvelle issue bien étiquetée
gh issue create --title "<module>: ..." --label "module:<x>,wave:<n>"

# Ajouter une issue au board (Project n°5)
gh project item-add 5 --owner marceaupatu123 \
  --url https://github.com/marceaupatu123/secure-horizons/issues/<N>
```

> Déplacer une carte entre colonnes (Todo / In Progress / Done) se fait le plus simplement **à la
> main dans l'interface du board**. L'important : la colonne doit refléter l'état réel.

### Phrase à donner à ton assistant IA

> « Quand je prends ou termine une tâche, rappelle-moi de m'assigner l'issue, de la déplacer sur
> le board (Project n°5) et de la fermer via `Closes #N` dans la PR. Si tu crées du travail
> nouveau, ouvre une issue avec les labels `module:*` et `wave:*` et ajoute-la au board. »
