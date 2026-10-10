---
inclusion: fileMatch
fileMatchPattern: 'llm/**'
---

# Périmètre module `llm`

Règles chargées automatiquement quand un fichier de `llm/` est en contexte.

- Tu ne modifies que `llm/`. Ne touche pas à `shared/` ni à `docs/CONTRACTS.md` sans accord.
- Rôle : appels Amazon Bedrock via l'API **Converse** (boto3), PAS l'API Anthropic directe.
  Région `us-east-1`, modèle via `BEDROCK_MODEL_ID` (.env) — ne jamais deviner l'id. Squelette :
  `llm/client.py`.
- Respecte le `shared.rate_limiter.RateLimiter` (~1 req/s/personne). Le LLM est appelé
  UNIQUEMENT sur alerte, jamais en boucle serrée.
- Données fictives uniquement. Chaque nouvelle fonction arrive avec son test (mock boto3) dans
  `llm/tests/`.
