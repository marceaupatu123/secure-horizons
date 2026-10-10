---
inclusion: fileMatch
fileMatchPattern: 'response/**'
---

# Périmètre module `response`

Règles chargées automatiquement quand un fichier de `response/` est en contexte.

- Tu ne modifies que `response/`. Importe les modèles depuis `shared.models` ; ne touche pas à
  `shared/` ni à `docs/CONTRACTS.md` sans accord explicite.
- Rôle : orchestration de la réponse graduée — gel (veto asymétrique : on ralentit, on n'accélère
  pas), validation humaine (multisig) pour lever un gel, journal d'audit DORA, publication sur la
  balise de risque si retenue. Squelette : `response/orchestrator.py`.
- L'IA ne décide JAMAIS seule d'un blocage. Les règles « quel cas → gel auto / validation
  humaine » sont une décision d'équipe (`docs/OPEN_QUESTIONS.md`, issues #17, #18, #19).
- Chaque nouvelle fonction arrive avec son test dans `response/tests/`.
