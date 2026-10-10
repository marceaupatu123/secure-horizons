---
inclusion: fileMatch
fileMatchPattern: 'shared/**'
---

# Périmètre module `shared` (SENSIBLE)

Règles chargées automatiquement quand un fichier de `shared/` est en contexte.

- ⚠️ `shared/` est un dossier **partagé** : utilisé par tous les modules. On ne le modifie pas
  seul. Toute évolution des modèles passe par un accord d'équipe et une PR dédiée du propriétaire
  de `shared/`.
- Les CHAMPS des modèles (`shared/models.py`) ne sont PAS encore décidés : ce sont des coquilles
  vides (`extra="allow"`) tant que l'équipe n'a pas tranché. Procédure : acter dans
  `docs/CONTRACTS.md` → remplir le modèle → les autres font `git pull`. Voir issues #2, #3.
- `shared/config.py` et `shared/rate_limiter.py` sont stables : ne pas y mettre de secret en dur,
  ne pas assouplir le limiteur sans décision d'équipe.
- Chaque fonction arrive avec son test dans `shared/tests/`.
