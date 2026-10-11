---
inclusion: fileMatch
fileMatchPattern: 'response/**'
---

# Périmètre module `response`

Règles chargées automatiquement quand un fichier de `response/` est en contexte.

- Tu ne modifies que `response/`. Importe les modèles depuis `shared.models` ; ne touche pas à
  `shared/` ni à `docs/CONTRACTS.md` sans accord explicite.
- Rôle : orchestration de la réponse graduée. Implémenté dans `response/orchestrator.py`
  (`ResponseOrchestrator`, PR #56), selon la machine à états actée en `docs/OPEN_ANSWERS.md` §3 :
  `NORMAL → RETARDÉ → {NORMAL (expiration) | DÉTRUIT (multisig 2/3) | PAUSE_GLOBALE (3/3)}`.
- Vocabulaire acté (§3) : un surveillant / l'IA ne fait que **retarder** (allonger, jamais
  raccourcir, auto-expirant, plafonné par périmètre). Il ne décide jamais seul d'une
  **destruction** ni d'une **pause globale** : ses demandes `confirm` restent des propositions.
  Ne pas introduire de chemin qui contourne ce veto asymétrique.
- Le multisig est **simulé** hors chaîne (`ResponsePolicy.guardians`) : le présenter comme tel.
  Le budget de quarantaine (§9) n'est pas appliqué ici (relève du contrat, #6).
- Les valeurs par défaut (`ResponsePolicy`) sont des propositions de référence, **à mesurer** :
  ne pas les présenter comme des chiffres actés.
- Chaque nouvelle fonction arrive avec son test dans `response/tests/`. Démo : `python -m response`.
