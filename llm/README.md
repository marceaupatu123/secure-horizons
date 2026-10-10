# llm

- **Rôle** : appels LLM via **Amazon Bedrock** (API Converse) pour **expliquer une alerte** et
  **pré-rédiger un rapport d'incident** (rubriques inspirées de DORA). **L'IA ne décide rien** :
  elle explique et rédige. Seule action possible côté surveillant/IA : **retarder** (auto-expirant) ;
  détruire = multisig 2/3, pause globale = multisig 3/3.
- **Propriétaire** : @denybs (voir `docs/TEAM.md`).

## Fichiers

- `client.py` : `BedrockClient` — `complete(user_text, system_prompt)` (un appel Converse, lève
  `LLMError`) et `explain(alert)` (texte de repli en cas d'échec). Client boto3 injectable.
- `prompts.py` : prompts système (français) et mise en forme des faits d'une `Alert`.
- `report.py` : `IncidentReport` (Pydantic, local au module), `build_incident_report(...)`,
  rendu `to_markdown()`.
- `demo.py` : alerte, actions et journal **fictifs** + faux client Converse hors ligne.

## Lancer

- `python -m llm` : démo **hors ligne** par défaut (aucun appel AWS, pas de `.env` requis).
- `python -m llm --live` ou `LLM_LIVE=1` : appel Bedrock réel. Requiert un `.env` renseigné
  (les 4 variables de `shared.config` : `AWS_REGION`, `BEDROCK_MODEL_ID`, `FUJI_RPC_URL`,
  `GUARDIAN_PRIVATE_KEY`) et des identifiants AWS valides. Le modèle vient **uniquement** de
  `BEDROCK_MODEL_ID`.

## Tester

`python -m pytest llm -q` — boto3 est remplacé par un faux client, **aucun appel réseau**.

## Garde-fous

- Limiteur `shared.rate_limiter` (≈ 1 req/s) avant **chaque** appel ; LLM appelé uniquement sur
  alerte, jamais en boucle.
- **Un seul** appel par rapport ; **pas de nouvel essai** (botocore `max_attempts=1`).
  Si le LLM échoue, les champs narratifs sont « à compléter », les champs factuels restent remplis.
- Température basse, `maxTokens` borné, aucun chiffre inventé (montants en base units, repris tels
  quels).
- Le rapport est un **brouillon structuré d'après DORA**, **pas une déclaration conforme**.
  Données fictives uniquement.
- Appeler `build_incident_report` sur une alerte **confirmée** est à la charge de l'appelant
  (`Alert` n'a pas de champ de confirmation).
