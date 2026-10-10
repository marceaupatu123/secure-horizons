# CLAUDE.md — consignes pour les assistants IA du projet

## But du projet (5 lignes) — _proposé, à valider en équipe_

Constat (inspiré Resolv) : l'attaquant détient une clé valide et signe lui-même ses autorisations
de mint ; réagir **après coup** arrive trop tard. La sécurité doit donc vivre **dans le contrat**,
au moment où il valide l'autorisation — principe « une clé volée ne doit presque rien valoir ».
Trois volets proposés : **(1)** la signature autorise « traiter la demande n°X », le contrat
dérive lui-même le montant du dépôt on-chain ; **(2)** perte maximale **bornée et testée** (tests
d'invariants/fuzzing Foundry, jamais « prouvée ») ; **(3)** pare-feu de contagion (balise de
risque + faux marché de prêt). Renforts : quarantaine à veto asymétrique, surveillants multiples,
IA simple surveillant. Données **fictives** uniquement.

## Principe de conception — _proposé, à valider en équipe_

> La sécurité vit dans le contrat ; la surveillance est un renfort ; l'IA ne décide jamais seule
> d'un blocage ; on ne promet que ce qu'on mesure.

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
