---
inclusion: fileMatch
fileMatchPattern: 'data/**'
---

# Périmètre module `data`

Règles chargées automatiquement quand un fichier de `data/` est en contexte.

- Tu ne modifies que `data/`. Importe les modèles depuis `shared.models` ; ne touche pas à
  `shared/` ni à `docs/CONTRACTS.md` sans accord explicite.
- **Données FICTIVES uniquement** : adresses et hash tirés d'un générateur à graine fixe, jamais de
  vraie adresse, clé ou donnée on-chain.
- Format acté (`docs/OPEN_ANSWERS.md` §6) : **JSONL**, une ligne = un modèle de `shared.models`
  sérialisé par Pydantic. Ne jamais redéfinir un schéma à côté des modèles partagés.
- Reproductibilité : même graine ⇒ mêmes fichiers. Tout nouveau tirage passe par le `random.Random`
  de la simulation, jamais par `random` global ni par l'horloge machine.
- Les paramètres de génération ne sont **pas** des mesures (`docs/CLAIMS.md`). Seuls les résultats
  calculés sur les jeux générés (manifestes) peuvent être présentés comme « mesurés sur données
  synthétiques ».
- Sorties dans `data/generated/` : ne pas les committer tant que l'équipe n'a pas tranché.
- Chaque nouvelle fonction arrive avec son test dans `data/tests/`. Lancer : `make data`.
