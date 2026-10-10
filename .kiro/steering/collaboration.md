# Règles de collaboration — Équipe 20 (Guardians of Value)

Ce fichier de steering est toujours inclus. Il reprend les règles de `CLAUDE.md` pour les
assistants travaillant dans Kiro.

## But du projet — _proposé, à valider en équipe_

Constat (inspiré Resolv) : l'attaquant détient une clé valide et signe lui-même ses mints ;
réagir **après coup** arrive trop tard. La sécurité doit vivre **dans le contrat** (« une clé
volée ne doit presque rien valoir »). Trois volets proposés : **(1)** la signature autorise
« traiter la demande n°X », le contrat dérive le montant du dépôt on-chain ; **(2)** perte
maximale **bornée et testée** (invariants/fuzzing Foundry, jamais « prouvée ») ; **(3)** pare-feu
de contagion (balise de risque + faux marché de prêt). Renforts : **quarantaine liquide
(« Token Ghost »)** — au lieu d'un sas strict, **tout transfert** émet un **Token Ghost librement échangeable**
converti 1:1 contre le vrai token après un délai sans anomalie, et **détruit** si un gel est
confirmé ; surveillants multiples ; IA simple surveillant. Données **fictives** uniquement.
**Décision du 2026-10-10** : le Ghost n'est **pas** limité au mint — **tout transfert** émet du
Ghost (ex. fenêtre 10 min). Voir `docs/OPEN_QUESTIONS.md` §0bis pour la décision et les
conséquences ouvertes (liquidité, compatibilité AMM, destruction en chaîne).

## Principe de conception — _proposé, à valider en équipe_

> La sécurité vit dans le contrat ; la surveillance est un renfort ; l'IA ne décide jamais seule
> d'un blocage ; on ne promet que ce qu'on mesure.
>
> **Quarantaine liquide (Token Ghost)** : la sécurité du protocole est garantie par le **transfert
> du risque vers un marché secondaire spéculatif** — le vrai token n'est jamais émis
> frauduleusement, et la perte éventuelle est assumée par les acheteurs de Tokens Ghost.
>
> Le Ghost portant **tous les transferts** (décision du 2026-10-10), il sert aussi à **récupérer
> des fonds après coup**. Le coût assumé est une **friction permanente** sur les usages
> légitimes : à **mesurer**, jamais à estimer (voir `docs/CLAIMS.md`).

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
- **Suivi des tâches** : quand on prend ou termine une tâche, penser à mettre à jour l'issue
  GitHub (s'assigner, fermer via `Closes #N` dans la PR) et le board (Project n°5). Toute tâche
  nouvelle = une issue avec labels `module:*` et `wave:*`, ajoutée au board. Détails et commandes
  dans `docs/AI_WORKFLOW.md`. En tant qu'assistant, rappeler ces gestes à l'utilisateur.

## Consigne de périmètre (IMPORTANT)

> Tu ne modifies que le dossier du module qui t'est assigné. Tu ne touches pas à `/shared` ni à
> `/docs/CONTRACTS.md` sans que je te le demande explicitement.

Aucune décision de conception (archi, algorithmes, seuils, design du contrat) n'est tranchée par
l'assistant : toute décision ambiguë va dans `docs/OPEN_QUESTIONS.md`.

Dès qu'une question reçoit une réponse actée par l'équipe (marquée **DÉCISION**, avec date et
auteur), elle est **copiée** dans `docs/OPEN_ANSWERS.md` (ligne d'index + texte), et la question
d'origine dans `OPEN_QUESTIONS.md` reçoit un renvoi « → Tranché, voir `docs/OPEN_ANSWERS.md` ».
Une proposition « à confirmer » n'y va pas tant que l'équipe ne l'a pas validée.
