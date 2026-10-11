# shared

- **Rôle** : **modèles de données communs** (Pydantic) partagés entre modules. Interfaces décrites dans `docs/CONTRACTS.md` (15 modèles ; `AdminEvent`, `SupplySnapshot` et les champs de demande de `MintEvent` viennent de la révision groupée #104).
- **Propriétaire** : @marceaupatu123 (voir `docs/TEAM.md`). ⚠️ Dossier sensible : ne pas modifier sans accord explicite (review de 2 propriétaires : @marceaupatu123 @denybs).
- **Lancer** : rien à lancer (bibliothèque) ; tests : `python -m pytest shared/`.
