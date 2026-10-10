---
inclusion: fileMatch
fileMatchPattern: 'contracts/**'
---

# Périmètre module `contracts`

Règles chargées automatiquement quand un fichier de `contracts/` est en contexte.

- Tu ne modifies que `contracts/`. Ne touche pas aux autres modules, ni à `shared/`, ni à
  `docs/CONTRACTS.md` sans accord explicite.
- Pas de code pour l'instant si les décisions d'archi ne sont pas tranchées : la conception du
  contrat (montant dérivé on-chain, plafonds, quarantaine, multisig, Token Ghost) est une décision
  d'équipe — voir `docs/OPEN_QUESTIONS.md` (issues GitHub #1, #3).
- Livrables envisagés : contrat vulnérable, contrat protégé (volet 1), tests invariants/fuzzing
  (volet 2), balise de risque + faux marché (volet 3), ERC20 Token Ghost. Détails :
  `contracts/README.md`.
- Jamais de vraie clé privée : comptes de test Fuji uniquement. `out/`, `cache/`, `broadcast/`
  sont déjà gitignorés.
- Dire « vérifié par tests d'invariants », jamais « prouvé ». Aucun chiffre non mesuré (voir
  `docs/CLAIMS.md`).
