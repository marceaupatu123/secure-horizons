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
   `docs/OPEN_QUESTIONS.md`, on tranche en équipe.
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
| `docs/CLAIMS.md` | Ce qu'on dira au jury + comment on le vérifie (aucun chiffre sans mesure). |
| `.github/pull_request_template.md` | Le gabarit à remplir pour chaque PR. |

En cas de doute : demande dans le canal d'équipe **avant** de laisser l'IA modifier quoi que ce
soit hors de ton dossier.
