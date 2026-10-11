# Ghost — Guardians of Value (Équipe 20)

> ESSECKATHON — Track « Fintech Security : Guardians of Value ». Hackathon 48h.
>
> 📖 **Doc illustrée en ligne (Mintlify) :** <https://cryptosecure.mintlify.site/>
> **Démo interactive (streamlit)** <https://secure-horizon-crypto-secure.streamlit.app/Demo_interactive>

Ce README explique **tout le projet et tout l'outillage** mis en place. Si tu débarques, lis-le
en entier une fois : il te dit quoi faire, dans quel ordre, et comment on travaille à plusieurs.

> ℹ️ **Nom.** Le projet s'appelle désormais **Ghost** (le jeton de quarantaine « Token Ghost » lui
> a donné son nom). L'identifiant du dépôt GitHub reste `marceaupatu123/secure-horizons` : on ne
> change pas les URLs de clone ni les liens d'issues pour ne rien casser.

---

## 1. Le projet en bref

Système de défense contre un exploit DeFi, inspiré du hack Resolv (mars 2026 : clé de signature
compromise, mint de tokens non collatéralisés, puis sortie des fonds).

**Principe** : comme l'attaquant détient une clé valide, réagir *après coup* arrive trop tard.
Donc **la sécurité vit dans le contrat** — « une clé volée ne doit presque rien valoir ». Trois
volets :

1. **Montant dérivé on-chain** : la signature autorise seulement « traiter la demande n°X », et le
   contrat calcule lui-même le montant à émettre à partir du dépôt enregistré. L'attaquant ne peut
   plus choisir un montant arbitraire.
2. **Perte maximale bornée et testée** : « même avec les clés volées, la perte max est de X $ »,
   vérifié par tests d'invariants/fuzzing Foundry. On dit « vérifié par tests », **jamais
   “prouvé”**.
3. **Pare-feu de contagion** : une « balise de risque » où les surveillants publient un gel, et un
   faux marché de prêt qui cesse d'accepter le token gelé.

### Le cœur : la quarantaine liquide « Token Ghost »

**Tout transfert** (pas seulement les mints — décision du 2026-10-10) émet un **Token Ghost**
librement échangeable, converti 1:1 contre le vrai token après un délai sans anomalie, et
**détruit** si un gel est confirmé. La sécurité du protocole repose sur le **transfert du risque
vers un marché secondaire spéculatif** : le vrai token n'est jamais émis frauduleusement, et la
perte éventuelle est assumée par les acheteurs de Tokens Ghost.

Le Ghost portant tous les transferts, il sert aussi à **récupérer des fonds après coup**
(séquestre à la source, lignée d'origine, saisie/clawback multisig).

En renfort : **surveillants** multiples (règles, ML, transferts anormaux) qui peuvent demander un
gel **sans jamais décider seuls**, une IA qui ne fait que **retarder** (localement, auto-expirant)
et ne décide jamais seule d'une destruction ni d'une pause globale (multisig humain), journal
d'audit **DORA** et rapport d'incident.

Les décisions ouvertes sont dans `docs/OPEN_QUESTIONS.md`, celles déjà tranchées dans
`docs/OPEN_ANSWERS.md`, l'ordre de travail dans `docs/ROADMAP.md`.

**Toutes les données sont fictives.** Jamais de vraie clé ni de vraies données.

---

## 2. Démarrage rapide (chaque membre, dans l'ordre)

```bash
# 1. Cloner (l'identifiant du dépôt reste "secure-horizons")
git clone https://github.com/marceaupatu123/secure-horizons.git
cd secure-horizons

# 2. Créer son environnement Python et installer les dépendances
python -m venv .venv
# Windows : .venv\Scripts\activate   |   macOS/Linux : source .venv/bin/activate
make install        # installe les deps ET active le hook anti-secrets (indispensable)

# 3. Fichier d'environnement local (jamais commité)
cp .env.example .env            # Windows : copy .env.example .env
#   puis remplir .env avec des valeurs de TEST uniquement

# 4. GitHub CLI (pour que Kiro mette à jour les issues/board tout seul)
winget install GitHub.cli       # si pas déjà installé
gh auth login                   # se connecter à GitHub

# 5. Sa branche de travail (jamais de travail direct sur main)
git checkout -b <prenom>/<module>
```

Puis **vérifier son accès RPC Fuji + faucet AVAX de test** et le `BEDROCK_MODEL_ID` (voir
`docs/TEAM.md`). Lire **`docs/AI_WORKFLOW.md`** avant de coder.

> ⚠️ `make install` active le pre-commit hook anti-secrets. Lance-le **avant ton premier commit**.

Vérifier que tout marche :

```bash
make test        # tous les tests doivent passer (au moins un test de fumée par module)
```

> `make` pas installé sous Windows ? Soit `winget install GnuWin32.Make` / Git Bash / WSL, soit
> lancer les commandes à la main (`python -m pip install -r requirements.txt`, `python -m pytest -q`…).

---

## 3. Structure du dépôt

| Dossier / fichier | Rôle |
|-------------------|------|
| `contracts/` | Smart contracts Solidity (Foundry), cible Avalanche Fuji. Montant dérivé on-chain + garde-fou du taux (`proposeRate` borné, timelock, cancel guardian). |
| `monitor/` | Écoute on-chain des événements de mint ET de transfert, lit la provenance du mint. |
| `detection/` | Surveillants d'anomalies (mint et transferts) qui produisent des alertes. |
| `llm/` | Appels LLM via Amazon Bedrock (API Converse) : explications, rapport d'incident. |
| `response/` | Orchestration de la réponse graduée (gel, validation humaine, journal). |
| `dashboard/` | Interface de démo métier (Streamlit) : vitrine + pages de détail (alertes, périmètres/gel, quarantaine Ghost, journal d'audit). |
| `shared/` | Code commun : config (`.env`), limiteur Bedrock, modèles de données (`MintEvent`, `AdminEvent`, `SupplySnapshot`). **Zone sensible.** |
| `data/` | Générateur de données synthétiques (fictives, JSONL) + marché du Ghost (décote/commission) + séquestre/saisie : `make data`. |
| `docs/` | Toute la doc d'équipe (voir §7). |
| `docs-site/` | Doc grand public illustrée (Mintlify) — en ligne sur <https://cryptosecure.mintlify.site/>. |
| `tools/` | Outils d'équipe hors modules (ex. dashboard d'avancement). |
| `.github/` | CI (GitHub Actions), gabarit de PR, CODEOWNERS. |
| `.githooks/` | Hook git pre-commit anti-secrets. |
| `.kiro/` | Config Kiro partagée : steering (règles), hooks (automatisations). |

Chaque module a un `README.md` (rôle, propriétaire, comment le lancer) et un dossier `tests/`.
Chaque `python -m <module>` tourne seul.

---

## 4. Comment on travaille à plusieurs (règles d'or)

- **Un dossier = un propriétaire.** On ne modifie pas le module d'un autre sans le prévenir.
- **`shared/` et `docs/CONTRACTS.md` sont partagés** : on n'y touche pas seul (ça casse tout le
  monde). On en discute, puis le propriétaire de `shared/` fait la PR.
- **Pas de travail direct sur `main`.** Une branche par personne/fonctionnalité
  (`<prenom>/<module>` ou `feat/<n°issue>-...`).
- **Petits commits, push + PR au moins toutes les heures.** Le compte AWS est supprimé à la fin :
  **GitHub est notre seule sauvegarde.**
- **Jamais de vraie clé ni de vraies données.** Comptes de test Fuji + synthétique
  (ex. faux secret `FLAG{team20-canary}`).
- **Aucune dépendance ajoutée sans la mettre dans `requirements.txt`** et prévenir l'équipe.
- **Chaque nouvelle fonction arrive avec son test.**

---

## 5. Le flux de travail d'une tâche (de bout en bout)

1. **Choisir une issue** sur GitHub, en commençant par la vague en cours (voir `docs/ROADMAP.md`).
2. **S'assigner l'issue** : `gh issue edit <N> --add-assignee "@me"`.
3. **Créer sa branche** : `git checkout -b feat/<N>-<description>`.
4. **Coder dans son module** + **ajouter des tests** dans `<module>/tests/`.
5. **Commits** : petits, fréquents. Le hook anti-secrets tourne tout seul à chaque commit.
6. **Ouvrir une PR** : `gh pr create --fill`, et mettre **`Closes #<N>`** dans la description.
   → au merge, l'issue se ferme et la carte du board passe en *Done* automatiquement.
7. **Attendre le CI vert** (obligatoire pour merger) puis fusionner.

Si tu utilises **Kiro**, ton assistant est configuré pour faire les gestes GitHub (assignation,
`Closes #N`, création d'issues) lui-même — voir `.kiro/steering/github-tracking.md`.

---

## 6. Outillage automatique (ce qui te protège sans y penser)

| Mécanisme | Ce qu'il fait | Où |
|-----------|---------------|----|
| **Pre-commit hook** | Refuse un commit contenant un `.env` ou une clé privée (hex 64 car.). `.env.example` autorisé. | `.githooks/pre-commit`, activé par `make install`. |
| **CI GitHub Actions** | Sur chaque PR : installe les deps, lint (`compileall`) et `pytest`. Rouge = on ne merge pas. | `.github/workflows/ci.yml` |
| **Branch protection sur `main`** | PR obligatoire + CI vert requis avant merge. Pas de push direct. | Réglé côté GitHub. |
| **Board automatique** | Issue/PR fermée → carte en *Done*. PR mergée → *Done*. | GitHub Project n°5. |
| **Hook Kiro `pytest-on-save`** | Lance `pytest` à chaque sauvegarde d'un `.py`. | `.kiro/hooks/` |
| **Steering Kiro** | Règles chargées automatiquement par l'assistant : collab, règles par module, suivi GitHub. | `.kiro/steering/` |

### Suivi du projet (issues + board + roadmap)

- **Issues** : <https://github.com/marceaupatu123/secure-horizons/issues> — étiquetées par module
  (`module:*`) et par ordre (`wave:0` … `wave:5`).
- **Board (Kanban)** : <https://github.com/users/marceaupatu123/projects/5> — Todo / In Progress /
  Done, mis à jour en partie tout seul.
- **ROADMAP** : `docs/ROADMAP.md` — l'ordre de travail en vagues (quoi faire avant quoi).

### Tableau de bord d'avancement (visuel)

```bash
make dashboard-progress     # ou : streamlit run tools/progress_dashboard.py
```
Ouvre une page web qui lit les issues GitHub et montre : progression globale, avancement par
vague, répartition par module, tâches en cours. **Lecture seule** (ne modifie rien). Nécessite
`gh` authentifié. Rafraîchir la page = actualiser.

---

## 7. Toute la documentation

> 🆕 **Nouveau sur le projet et novice en crypto ?** Commence par la doc illustrée **en ligne** :
> **<https://cryptosecure.mintlify.site/>** (Mintlify). Elle explique tout avec des analogies
> simples, en trois onglets : **« Comprendre le projet »**, **« Sous le capot »** et **« Mettre
> les mains dedans »**. Pour la lancer en local : `cd docs-site && mintlify dev`, ou lis
> directement les fichiers `.mdx`.

| Fichier | Contenu |
|---------|---------|
| **<https://cryptosecure.mintlify.site/>** | **Doc grand public illustrée (Mintlify), en ligne, pour comprendre le projet sans jargon.** Source : `docs-site/`. |
| `docs-site/` | Source de la doc Mintlify ci-dessus (`.mdx` + `docs.json`). |
| `docs/AI_WORKFLOW.md` | **Comment dialoguer avec ton IA sans empiéter sur les autres. À lire en premier.** |
| `docs/ROADMAP.md` | Ordre de travail en vagues + dépendances entre tâches. |
| `docs/TEAM.md` | Qui possède quel module, branches, contraintes AWS, checklist de démarrage. |
| `docs/OPEN_QUESTIONS.md` | Les décisions de conception encore à trancher en équipe. |
| `docs/OPEN_ANSWERS.md` | Les décisions déjà tranchées (datées, avec auteur). |
| `docs/CONTRACTS.md` | Interfaces entre modules (gabarits à remplir ensemble). **Zone sensible.** |
| `docs/CLAIMS.md` | Ce qu'on affirmera au jury + comment on le vérifie. Règle : aucun chiffre sans mesure. |
| `docs/GHOST_MARKET_SEIZURE.md` | Design du marché du Ghost (décote/commission) et de la saisie/clawback. |
| `CLAUDE.md` | But du projet, conventions de code, règles de collaboration (contexte pour l'IA). |

---

## 8. Contraintes AWS (à retenir)

- Compte AWS isolé, région **`us-east-1` uniquement**, **supprimé à la fin** du hackathon.
- LLM via **Amazon Bedrock** (boto3, API **Converse**), pas l'API Anthropic directe.
- Limite ≈ **1 requête/seconde/personne** → un limiteur est fourni (`shared/rate_limiter.py`), et
  le LLM n'est appelé **que sur alerte**.
- À vérifier tôt par chacun : accès RPC public Fuji, AVAX de test (faucet), `BEDROCK_MODEL_ID`
  exact (dans la console Bedrock, ne pas deviner).

  La démo: https://secure-horizon-crypto-secure.streamlit.app/Demo_interactive
