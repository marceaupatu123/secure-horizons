# Secure Horizons — Guardians of Value (Équipe 20)

Système de détection et de réponse automatique à un exploit DeFi, inspiré du hack Resolv
(mars 2026 : clé de signature compromise, mint de ~80M de tokens non collatéralisés, puis
sortie des fonds). On surveille **deux moments** de l'attaque : le **mint anormal** (trop de
tokens pour le collatéral) et les **transferts anormaux** (gros montants vers adresses neuves,
découpage, sorties rapides vers des échanges). La réponse est **graduée** (alerte → pause
réversible → validation humaine) et complétée par une dimension **conformité DORA** (journal
d'audit, rapport d'incident pré-rempli).

> ESSECKATHON — Track « Fintech Security : Guardians of Value ». Hackathon 48h.

## Démarrage rapide (chaque membre)

```bash
# 1. Cloner
git clone <url-du-repo>
cd secure-horizons

# 2. Créer son environnement et installer les dépendances
#    make install installe aussi le pre-commit hook (anti-secrets). INDISPENSABLE.
python -m venv .venv
# Windows : .venv\Scripts\activate   |   macOS/Linux : source .venv/bin/activate
make install

# 3. Créer son fichier d'environnement local (jamais commité)
cp .env.example .env        # Windows : copy .env.example .env
#    puis remplir .env avec des valeurs de TEST uniquement

# 4. Créer sa branche de travail (jamais de travail direct sur main)
git checkout -b <prenom>/<module>
```

> ⚠️ **`make install` active le pre-commit hook** qui refuse les fichiers `.env` et les clés
> privées. Lance-le avant ton premier commit, sinon le garde-fou anti-secrets n'est pas en place.

## Vérifier que tout fonctionne

```bash
make install   # dépendances + activation du hook
make test      # un test de fumée par module doit passer
```

## Structure

| Dossier       | Rôle                                                            |
|---------------|-----------------------------------------------------------------|
| `contracts/`  | Smart contracts Solidity (Foundry), cible Avalanche Fuji        |
| `monitor/`    | Écoute on-chain (événements de mint ET de transfert)            |
| `detection/`  | Détection d'anomalies (mint et transferts)                      |
| `llm/`        | Appels LLM (explications, rapport d'incident) via Amazon Bedrock |
| `response/`   | Orchestration de la réponse graduée                             |
| `dashboard/`  | Interface de démo (Streamlit)                                   |
| `shared/`     | Modèles de données communs                                      |
| `data/`       | Données synthétiques (fictives, voir `data/README.md`)          |
| `docs/`       | Documentation d'équipe                                          |

## Documentation d'équipe

- `docs/TEAM.md` — qui possède quel module, branches, contraintes AWS.
- `docs/CONTRACTS.md` — interfaces entre modules (à définir ensemble).
- `docs/OPEN_QUESTIONS.md` — décisions de conception à trancher en équipe.
- `CLAUDE.md` — but du projet, conventions de code, règles de collaboration.

## Règles d'or

- **Un dossier = un propriétaire.** On ne modifie pas le module d'un autre sans le prévenir.
- **Pas de travail direct sur `main`.** Une branche par personne/fonctionnalité.
- **Petits commits, push + PR au moins toutes les heures** (le compte AWS est supprimé à la fin
  de l'événement : GitHub est notre seule sauvegarde).
- **Jamais de vraie clé ni de vraies données.** Comptes de test Fuji + données synthétiques
  (ex : faux secret `FLAG{team20-canary}`).
