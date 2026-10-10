# llm

- **Rôle** : appels LLM via **Amazon Bedrock** (API Converse) pour explications et rapport d'incident.
- **Propriétaire** : @denybs (voir `docs/TEAM.md`).
- **Lancer** : `python -m llm` (à implémenter) ; tests : `python -m pytest llm/`. LLM appelé **sur alerte** uniquement (≈1 req/s/personne).
