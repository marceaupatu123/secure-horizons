---
inclusion: fileMatch
fileMatchPattern: 'monitor/**'
---

# Périmètre module `monitor`

Règles chargées automatiquement quand un fichier de `monitor/` est en contexte.

- Tu ne modifies que `monitor/`. Importe les modèles depuis `shared.models` sans les redéfinir ;
  ne touche pas à `shared/` ni à `docs/CONTRACTS.md` sans accord explicite.
- Rôle : écoute on-chain des mints et transferts (Fuji), production de `MintEvent` /
  `TransferEvent` pour `detection`. Squelette : `monitor/listener.py`.
- La connexion RPC lit `shared.config` (jamais de valeur en dur, jamais de vraie clé).
- Chaque nouvelle fonction arrive avec son test dans `monitor/tests/`. Lance `pytest` avant de
  commiter.
