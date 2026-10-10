---
inclusion: fileMatch
fileMatchPattern: 'dashboard/**'
---

# Périmètre module `dashboard`

Règles chargées automatiquement quand un fichier de `dashboard/` est en contexte.

- Tu ne modifies que `dashboard/`. Lis les modèles depuis `shared.models` ; ne touche pas à
  `shared/` ni à `docs/CONTRACTS.md` sans accord.
- Rôle : interface de démo Streamlit. Point d'entrée `dashboard/app.py`, lancé via
  `make run-dashboard`.
- Données **synthétiques** uniquement, jamais de vraies données ni de vraies adresses.
- Aucun chiffre affiché sans avoir été mesuré (voir `docs/CLAIMS.md`).
