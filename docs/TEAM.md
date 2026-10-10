# TEAM.md — organisation de l'équipe 20

## Répartition des modules

À compléter : un propriétaire par module, une branche par personne/fonctionnalité.

| Module       | Propriétaire | Branche                 |
|--------------|--------------|-------------------------|
| `contracts`  | _(à définir)_ | _(ex: `prenom/contracts`)_ |
| `monitor`    | _(à définir)_ | _(ex: `prenom/monitor`)_   |
| `detection`  | _(à définir)_ | _(ex: `prenom/detection`)_ |
| `llm`        | _(à définir)_ | _(ex: `prenom/llm`)_       |
| `response`   | _(à définir)_ | _(ex: `prenom/response`)_  |
| `dashboard`  | _(à définir)_ | _(ex: `prenom/dashboard`)_ |
| `shared`     | _(à définir)_ | _(ex: `prenom/shared`)_    |
| `data`       | _(à définir)_ | _(ex: `prenom/data`)_      |

> Pensez à reporter les propriétaires dans `.github/CODEOWNERS` **et** dans l'en-tête de chaque
> `README.md` de module.

## Règles de collaboration

- **Un dossier = un propriétaire.** On ne modifie pas le dossier d'un autre sans le prévenir.
- **Pas de travail direct sur `main`** : une branche par personne ou par fonctionnalité.
- **Petits commits, push et pull request au moins toutes les heures.** Le compte AWS est supprimé
  à la fin de l'événement, donc **GitHub est notre seule sauvegarde**.
- **Aucune dépendance** ajoutée sans l'ajouter à `requirements.txt` et prévenir l'équipe.
- **Jamais de vraie clé privée ni de vraies données** : comptes de test Fuji et données
  synthétiques uniquement (ex : faux secret `FLAG{team20-canary}`).
- **Chaque module doit pouvoir être lancé et testé seul.**
- **Appels Bedrock** : ≈ **1 requête/seconde/personne**. Prévoir un petit limiteur, ne jamais
  appeler le LLM en boucle serrée. Le LLM n'est appelé **que sur alerte**.
- `shared/` et `docs/CONTRACTS.md` sont **partagés** : on ne les modifie pas sans accord explicite.

## Contraintes AWS

- **Compte AWS isolé**, région **`us-east-1` uniquement**, **supprimé à la fin du hackathon**.
- **LLM via Amazon Bedrock** (boto3, **API Converse**) — **pas** via l'API Anthropic directe.
- On ne teste **que ce qu'on a déployé** dans notre propre compte.
- **À vérifier tôt** (chaque membre) :
  - accès réseau à un **RPC public Fuji** ;
  - **AVAX de test** récupéré via **faucet** pour chaque membre ;
  - `BEDROCK_MODEL_ID` : à **vérifier dans la console Bedrock**, ne pas deviner.

## Checklist de démarrage individuel

1. Cloner le repo.
2. `python -m venv .venv` puis activer l'environnement.
3. `make install` (installe les deps **et** active le pre-commit hook anti-secrets).
4. `cp .env.example .env` et remplir avec des valeurs de **test** uniquement.
5. `git checkout -b <prenom>/<module>`.
6. Vérifier son accès RPC Fuji + faucet AVAX de test.
