---
inclusion: fileMatch
fileMatchPattern: 'detection/**'
---

# Périmètre module `detection`

Règles chargées automatiquement quand un fichier de `detection/` est en contexte.

- Tu ne modifies que `detection/`. Importe les modèles depuis `shared.models` ; ne touche pas à
  `shared/` ni à `docs/CONTRACTS.md` sans accord explicite.
- Rôle : surveillants indépendants (règles, ML, signaux de transferts) qui renvoient `Alert | None`
  et peuvent demander un gel. L'IA n'est qu'un surveillant, jamais le décideur. Squelette :
  `detection/detector.py`.
- Les seuils, invariants et signaux ne sont PAS tranchés ici : propose des options, je les note
  dans `docs/OPEN_QUESTIONS.md` (issues #1, #11, #12).
- Chaque nouvelle fonction arrive avec son test dans `detection/tests/`.
