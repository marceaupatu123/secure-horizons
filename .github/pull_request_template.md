# Pull Request

## Quoi
<!-- Que fait cette PR, en une ou deux phrases ? -->

## Pourquoi
<!-- Quel besoin / problème / objectif ? Lien vers une OPEN_QUESTION si pertinent. -->

## Comment tester
<!-- Commandes exactes pour vérifier (ex : make test, python -m pytest monitor/). -->

## Modules touchés
<!-- Cocher les modules impactés. Un dossier = un propriétaire : prévenir si on touche celui d'un autre. -->
- [ ] contracts
- [ ] monitor
- [ ] detection
- [ ] llm
- [ ] response
- [ ] dashboard
- [ ] shared  _(sensible — accord explicite requis)_
- [ ] data
- [ ] docs

## Checklist
- [ ] **Chaque nouvelle fonction est accompagnée de ses tests** (voir ci-dessous).
- [ ] `make test` passe en local **et** le CI (GitHub Actions) est vert.
- [ ] Pas de vraie clé ni de vraies données (test Fuji + synthétique uniquement).
- [ ] Nouvelles dépendances ajoutées à `requirements.txt` et équipe prévenue.
- [ ] Je ne modifie pas `/shared` ni `/docs/CONTRACTS.md` sans accord explicite.

> Le workflow CI (`.github/workflows/ci.yml`) lance lint + `pytest` sur chaque PR.
> **On alimente les tests à chaque nouvelle action** : une PR sans test pour le code ajouté
> ne doit pas être fusionnée.
