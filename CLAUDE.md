# CLAUDE.md — consignes pour les assistants IA du projet

## But du projet (5 lignes) — _proposé, à valider en équipe_

Constat (inspiré Resolv) : l'attaquant détient une clé valide et signe lui-même ses autorisations
de mint ; réagir **après coup** arrive trop tard. La sécurité doit donc vivre **dans le contrat**,
au moment où il valide l'autorisation — principe « une clé volée ne doit presque rien valoir ».
Trois volets proposés : **(1)** la signature autorise « traiter la demande n°X », le contrat
dérive lui-même le montant du dépôt on-chain ; **(2)** perte maximale **bornée et testée** (tests
d'invariants/fuzzing Foundry, jamais « prouvée ») ; **(3)** pare-feu de contagion (balise de
risque + faux marché de prêt). Renforts : **quarantaine liquide (« Token Ghost »)** — au lieu d'un
sas strict, **tout transfert** émet un **Token Ghost librement échangeable** converti 1:1 contre
le vrai token après un délai sans anomalie (ex. 10 min), et **détruit** si un gel est confirmé
(décision du 2026-10-10 : le Ghost n'est **pas** limité au mint — voir
`docs/OPEN_QUESTIONS.md` §0bis) ; surveillants multiples ; IA simple surveillant. Données
**fictives** uniquement.

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

- **Python 3.11+**. Typage obligatoire (annotations de types sur les fonctions publiques).
- **Pydantic** pour les modèles de données partagés (dossier `shared/`).
- **Nommage** : `snake_case` pour fonctions/variables, `PascalCase` pour les classes,
  `UPPER_SNAKE_CASE` pour les constantes. Noms explicites, en anglais pour le code.
- **Tests simples** : `pytest`, un test de fumée par module au minimum. Chaque module doit
  pouvoir être lancé et testé seul.
- **Dépendances** : source unique dans `requirements.txt`. Aucune dépendance ajoutée sans la
  mettre dans `requirements.txt` **et** prévenir l'équipe.
- **Secrets** : jamais de vraie clé ni de vraie donnée. Comptes de test Fuji, données
  synthétiques, faux secrets de type `FLAG{team20-canary}` uniquement.

## Règles de collaboration

- **Un dossier = un propriétaire.** On ne modifie pas le dossier d'un autre sans le prévenir.
- **Pas de travail direct sur `main`** : une branche par personne ou par fonctionnalité.
- **Petits commits, push et pull request au moins toutes les heures** (le compte AWS est
  supprimé à la fin de l'événement, donc GitHub est notre seule sauvegarde).
- **Aucune dépendance** ajoutée sans l'ajouter à `requirements.txt` et prévenir l'équipe.
- **Jamais de vraie clé privée ni de vraies données** : comptes de test Fuji et données
  synthétiques uniquement.
- **Chaque module doit pouvoir être lancé et testé seul.**
- **Appels Bedrock** : limite d'environ **1 requête par seconde par personne**. Prévoir un petit
  limiteur et ne jamais appeler le LLM en boucle serrée. Le LLM n'est appelé **que sur alerte**.

## Consigne de périmètre (IMPORTANT)

> Tu ne modifies que le dossier du module qui t'est assigné. Tu ne touches pas à `/shared` ni à
> `/docs/CONTRACTS.md` sans que je te le demande explicitement.

Les choix de conception (architecture, algorithmes, seuils, design du contrat) ne sont **pas**
tranchés par l'assistant : toute décision ambiguë va dans `docs/OPEN_QUESTIONS.md`.

Dès qu'une question reçoit une réponse actée par l'équipe (marquée **DÉCISION**, avec date et
auteur), elle est **copiée** dans `docs/OPEN_ANSWERS.md` (ligne d'index + texte), et la question
d'origine dans `OPEN_QUESTIONS.md` reçoit un renvoi « → Tranché, voir `docs/OPEN_ANSWERS.md` ».
Une proposition « à confirmer » n'y va pas tant que l'équipe ne l'a pas validée.
