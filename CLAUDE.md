# CLAUDE.md — consignes pour les assistants IA du projet

## But du projet (5 lignes)

Détecter et répondre automatiquement à un exploit DeFi, inspiré du hack Resolv (clé compromise,
mint massif de tokens non collatéralisés, puis sortie des fonds). On surveille deux moments :
le **mint anormal** (trop de tokens par rapport au collatéral) et les **transferts anormaux**
(gros montants vers adresses neuves, découpage, sorties rapides). La réponse est **graduée**
(alerte → pause réversible → validation humaine), avec une dimension conformité **DORA**
(journal d'audit, rapport d'incident pré-rempli). Toutes les données sont fictives.

## Conventions de code

- **Python 3.11+**. Typage obligatoire (annotations de types sur les fonctions publiques).
- **Pydantic** pour les modèles de données partagés (dossier `shared/`).
- **Nommage** : `snake_case` pour fonctions/variables, `PascalCase` pour les classes,
  `UPPER_SNAKE_CASE` pour les constantes. Noms explicites, en anglais pour le code.
- **Tests simples** : `pytest`, un test de fumée par module au minimum. Chaque module doit
  pouvoir être lancé et testé seul.
- **Dépendances** : source unique dans `requirements.txt`. Aucune dépendance ajoutée sans la
  mettre dans `requirements.txt` **et** prévenir l'équipe.
- **Secrets** : jamais de vraie clé ni de vraie donnée. Comptes de test Fuji, données
  synthétiques, faux secrets de type `FLAG{team20-canary}` uniquement.

## Règles de collaboration

- **Un dossier = un propriétaire.** On ne modifie pas le dossier d'un autre sans le prévenir.
- **Pas de travail direct sur `main`** : une branche par personne ou par fonctionnalité.
- **Petits commits, push et pull request au moins toutes les heures** (le compte AWS est
  supprimé à la fin de l'événement, donc GitHub est notre seule sauvegarde).
- **Aucune dépendance** ajoutée sans l'ajouter à `requirements.txt` et prévenir l'équipe.
- **Jamais de vraie clé privée ni de vraies données** : comptes de test Fuji et données
  synthétiques uniquement.
- **Chaque module doit pouvoir être lancé et testé seul.**
- **Appels Bedrock** : limite d'environ **1 requête par seconde par personne**. Prévoir un petit
  limiteur et ne jamais appeler le LLM en boucle serrée. Le LLM n'est appelé **que sur alerte**.

## Consigne de périmètre (IMPORTANT)

> Tu ne modifies que le dossier du module qui t'est assigné. Tu ne touches pas à `/shared` ni à
> `/docs/CONTRACTS.md` sans que je te le demande explicitement.

Les choix de conception (architecture, algorithmes, seuils, design du contrat) ne sont **pas**
tranchés par l'assistant : toute décision ambiguë va dans `docs/OPEN_QUESTIONS.md`.
