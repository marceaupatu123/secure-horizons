# Règles de collaboration — Équipe 20 (Guardians of Value)

Ce fichier de steering est toujours inclus. Il reprend les règles de `CLAUDE.md` pour les
assistants travaillant dans Kiro.

## But du projet — _proposé, à valider en équipe_

Constat (inspiré Resolv) : l'attaquant détient une clé valide et signe lui-même ses mints ;
réagir **après coup** arrive trop tard. La sécurité doit vivre **dans le contrat** (« une clé
volée ne doit presque rien valoir »). Trois volets proposés : **(1)** la signature autorise
« traiter la demande n°X », le contrat dérive le montant du dépôt on-chain ; **(2)** perte
maximale **bornée et testée** (invariants/fuzzing Foundry, jamais « prouvée ») ; **(3)** pare-feu
de contagion (balise de risque + faux marché de prêt). Renforts : quarantaine à veto asymétrique,
surveillants multiples, IA simple surveillant. Données **fictives** uniquement.

## Principe de conception — _proposé, à valider en équipe_

> La sécurité vit dans le contrat ; la surveillance est un renfort ; l'IA ne décide jamais seule
> d'un blocage ; on ne promet que ce qu'on mesure.

## Conventions de code

- Python 3.11+, typage obligatoire sur les fonctions publiques.
- Pydantic pour les modèles partagés (`shared/`).
- `snake_case` (fonctions/variables), `PascalCase` (classes), `UPPER_SNAKE_CASE` (constantes).
- `pytest`, un test de fumée par module. Chaque module se lance et se teste seul.
- Dépendances uniquement via `requirements.txt`.

## Règles de collaboration

- Un dossier = un propriétaire ; on ne touche pas au module d'un autre sans prévenir.
- Pas de travail direct sur `main` : une branche par personne/fonctionnalité.
- Petits commits, push + PR au moins toutes les heures (GitHub = seule sauvegarde).
- Aucune dépendance sans l'ajouter à `requirements.txt` + prévenir l'équipe.
- Jamais de vraie clé ni de vraies données (test Fuji + synthétique uniquement).
- Appels Bedrock ≈ 1 req/s/personne, limiteur obligatoire, LLM appelé seulement sur alerte.

## Consigne de périmètre (IMPORTANT)

> Tu ne modifies que le dossier du module qui t'est assigné. Tu ne touches pas à `/shared` ni à
> `/docs/CONTRACTS.md` sans que je te le demande explicitement.

Aucune décision de conception (archi, algorithmes, seuils, design du contrat) n'est tranchée par
l'assistant : toute décision ambiguë va dans `docs/OPEN_QUESTIONS.md`.
