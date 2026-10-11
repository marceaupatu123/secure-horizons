# Script du pitch — Équipe 20, Crypto-Secure

**Format round 1** : 5 min de pitch + 2 min de questions, jury d'au moins 3 experts.
**Deck** : 8 slides max. **Finale** : 3 min + 3 min (version courte en bas de page).

Règles de parole : aucun chiffre non mesuré ; « vérifié par tests », jamais « prouvé » ; dire
« données fictives » et « simulation » sans s'en excuser.

| # | Slide | Durée | Critère de la grille visé |
|---|-------|-------|---------------------------|
| 1 | Titre et accroche | 0:20 | Pitch |
| 2 | Le problème | 0:35 | Pitch |
| 3 | Notre solution | 0:50 | Faisabilité |
| 4 | Démo en direct | 1:20 | Détection, Réponse |
| 5 | Ce qu'on a mesuré | 0:40 | Détection (30 %) |
| 6 | Conformité et explicabilité | 0:30 | Conformité (15 %) |
| 7 | Pour qui, et quel modèle | 0:25 | Faisabilité |
| 8 | Équipe, limites, suite | 0:20 | Pitch |

---

## Slide 1 — Titre et accroche (0:20)

**À l'écran** : « Crypto-Secure — une clé volée ne doit presque rien valoir ». Équipe 20,
Track 1.

**À dire** : « Protocole Resolv. Un attaquant dépose environ 200 000 dollars et minte
80 millions de jetons. Dix-sept minutes plus tard, le stablecoin a perdu son ancrage. Il n'a
cassé aucune cryptographie : il avait une clé valide. »

> Les montants et les 17 minutes viennent de `docs-site/promesses-jury.mdx`. Ajouter la date
> du hack seulement si quelqu'un l'a vérifiée.

## Slide 2 — Le problème (0:35)

**À l'écran** : une frise « signature valide → mint → dépeg en 17 min → alerte… trop tard ».
Une phrase : « Surveiller autour du contrat ne suffit pas. »

**À dire** : « Dans ce type d'attaque, tout est légitime du point de vue du contrat : la
signature est bonne. Un outil de surveillance classique voit le problème après le mint, quand
les jetons sont déjà vendus. En DeFi un exploit se joue en minutes, plus vite qu'une équipe
humaine ne peut décider. Réagir après coup arrive trop tard. Notre question : comment faire
pour qu'une clé volée ne vaille presque rien ? »

## Slide 3 — Notre solution (0:50)

**À l'écran** : trois blocs + un bandeau.
1. **Le contrat dérive le montant** du dépôt on-chain.
2. **Perte maximale bornée**, vérifiée par tests d'invariants.
3. **Pare-feu de contagion** : balise de risque lue par les protocoles en aval.
Bandeau : **Token Ghost** — tout transfert passe par un jeton d'attente, converti 1:1 après
10 min sans anomalie, détruit si la fraude est confirmée.

**À dire** : « Trois protections, dans le contrat. Un : la signature n'autorise plus un
montant, elle autorise à traiter la demande numéro X, et le contrat calcule lui-même le
montant à partir du dépôt. Deux : la perte maximale est bornée, et on le vérifie par fuzzing.
Trois : une balise de risque que les protocoles de prêt peuvent lire pour refuser une garantie
suspecte. Et pour l'attaquant qui passe quand même : le Token Ghost. Tout transfert émet
d'abord un jeton d'attente, librement échangeable, qui ne devient du vrai jeton qu'après dix
minutes sans alerte. Ces dix minutes, c'est le temps qu'on achète aux défenseurs. »

## Slide 4 — Démo en direct (1:20)

**À l'écran** : le dashboard, page « Scénarios de démo », seed 20. Slide de secours : la
vidéo de 2-3 min.

**À dire et à faire** :
- **Scénario A (0:20)** — « Même attaque sur deux contrats. Le vulnérable émet mille fois le
  dépôt. Le protégé émet exactement le dépôt : perte du protocole, zéro. »
- **Scénario B (0:40)** — « Attaquant plus malin : il reste sous les plafonds, le contrat
  seul ne rejette rien. Nos surveillants voient un volume élevé et une dispersion qui
  s'effondre : alerte 296 secondes après le mint, avant la fin de la fenêtre. La réponse
  retarde uniquement le périmètre suspect, moins de 2 % de l'offre. Deux signataires humains
  confirment, le Ghost suspect est détruit. Tout est au journal d'audit, et le rapport
  d'incident est pré-rempli. »
- **Scénario N3 (0:20)** — « Et si on se trompe ? Fausse alerte : personne ne confirme, le
  retard expire seul, rien n'est détruit. »

> Lire les chiffres affichés à l'écran s'ils diffèrent de ceux du script. Si la démo plante :
> passer à la vidéo sans commenter.

## Slide 5 — Ce qu'on a mesuré (0:40)

**À l'écran** : quatre chiffres, chacun avec sa source en petit.
- **0** perte protocole avec la clé de service volée (tests d'invariants Foundry)
- **296 s** de délai de détection, pour une fenêtre de 10 min (scénario B, seed 20)
- **0 faux positif sur 864** tranches de trafic normal (profil petits transferts)
- **Moins de 2 %** de l'offre touchée par la réponse ; **8 %** pour un faux positif, qui se
  résorbe seul
Mention : « données synthétiques, graines fixes, rejouables depuis le dépôt ».

**À dire** : « Chaque chiffre que vous voyez sort d'une commande du dépôt, rejouable. Sur un
autre profil de trafic, avec de gros transferts, on a des faux positifs aux seuils par
défaut : cinq, puis zéro en remontant le seuil. On vous le dit parce que c'est ce qu'on a
mesuré. Et notre surveillance a un coût permanent : environ 3 % de l'offre immobilisée en
Ghost à tout instant. »

## Slide 6 — Conformité et explicabilité (0:30)

**À l'écran** :
- **DORA** : détection, classification, journal d'audit horodaté, rapport d'incident
  pré-rempli selon les rubriques de notification d'incident majeur.
- **Qui décide quoi** : IA → retarde (réversible, expire seul) · humains 2/3 → détruisent ·
  humains 3/3 → pause globale.
- **Pour l'auditeur** : chaque décision a un auteur, une alerte d'origine, un quorum, une
  heure.

**À dire** : « Vous allez nous demander : si le modèle se trompe, qui est responsable ? Le
pire que notre IA puisse faire seule, c'est retarder une conversion, sur un périmètre ciblé,
pour une durée bornée. Toute action irréversible porte la signature d'au moins deux humains.
Le rapport DORA est un brouillon que l'humain relit, pas une déclaration automatique. »

## Slide 7 — Pour qui, et quel modèle (0:25)

**À l'écran** : cibles — émetteurs de stablecoins et d'actifs tokenisés, prestataires crypto
soumis à MiCA et DORA, protocoles de prêt en aval. Modèle : **commission à la sortie de
quarantaine** (conversion Ghost → vrai jeton) = **petit plancher fixe + supplément indexé sur le
ratio de contamination**. Le plancher rémunère l'opérateur, le supplément alimente un **fonds
d'assurance**. Les transferts et les swaps restent gratuits.

**À dire** : « Nos utilisateurs sont les émetteurs de jetons adossés et les protocoles qui
acceptent ces jetons en garantie. Nous opérons le protocole, et nous prenons une commission à
un seul moment : quand un Ghost sort de quarantaine et devient du vrai jeton. Un petit montant
fixe, plus un supplément qui monte avec le risque. Un utilisateur propre paie presque rien, un
Ghost suspect paie plus, et cette part va dans un fonds d'assurance qui couvre les
destructions. On fait payer le risque, pas l'usage. »

> **Proposé (2026-10-11, Yannis), à valider en équipe avant de monter la slide.** Précise la
> marge de conversion décidée en §0 (`docs/OPEN_ANSWERS.md`) : barème **plancher + indexé sur le
> ratio**, affectation **plancher → revenu, supplément → fonds d'assurance**. Choix du modèle
> **opérateur** (on opère le protocole et on encaisse la commission) plutôt que « standard
> ouvert, chaque émetteur déploie son instance », qui ferait revenir la commission à
> l'émetteur. Reste compatible avec la §10bis : rien n'est prélevé sur l'argent saisi et
> restitué aux victimes. **Aucun taux n'est annoncé** tant qu'il n'est pas mesuré
> (`docs/CLAIMS.md`).

## Slide 8 — Équipe, limites, suite (0:20)

**À l'écran** : les 4 membres et leurs modules ; trois limites ; trois pistes.
- Limites : clés d'administration supposées saines · pas de déploiement Fuji, rejeux en
  simulation et chaîne locale · la perte est reportée sur les acheteurs de Ghost, pas effacée.
- Suite : déploiement testnet · signatures à seuil (MPC) · enclave pour la clé.

**À dire** : « Ce qu'on ne couvre pas : une clé d'administration compromise, et une détection
plus lente que la fenêtre. Ce qu'on a construit en 36 heures : un contrat où une clé volée ne
choisit plus le montant, et dix minutes de sursis mesurées pour que des humains décident.
Merci. »

---

## Questions probables (2 min)

| Question | Réponse courte |
|----------|----------------|
| Si le modèle se trompe, qui est responsable ? | L'IA ne peut que retarder, ça expire seul (N3). Les actes irréversibles sont signés par 2 humains sur 3 et tracés. |
| Et si la clé d'administration est volée ? | Hors périmètre, on le dit. Pistes : MPC, enclave. La borne testée porte sur la clé de service. |
| Pourquoi pas déployé sur Fuji ? | Priorité donnée aux invariants et au rejeu reproductible sur chaîne locale. Le monitor sait écouter un contrat Fuji ; aucune adresse n'est déployée. |
| Qui perd de l'argent avec le Ghost ? | Ceux qui achètent du Ghost suspect en connaissance de cause. La perte n'est pas effacée, elle est reportée et ciblée par ratio. Tension avec DORA assumée. |
| Vos faux positifs ? | 0 sur 864 tranches sur un profil, 5 sur l'autre aux seuils bas. Dépend du profil de trafic, non tranché. |
| Et si la détection dépasse 10 min ? | Tout est converti. La marge est bornée par la tranche d'agrégation de 5 min ; la latence réseau réelle n'est pas mesurée. |
| Dix minutes d'attente, c'est acceptable ? | C'est le coût assumé : environ 3 % de l'offre immobilisée en médiane. Le Ghost reste échangeable pendant ce temps. |
| Le multisig est réel ? | Simulé dans la maquette, présenté comme tel. |
| Votre commission taxe les honnêtes ? | Presque pas : on ne prélève qu'à la sortie de quarantaine, jamais sur les transferts ni les swaps. Le plancher est petit ; le supplément suit le ratio de contamination, donc un Ghost propre ne paie que le plancher. |
| Vous gagnez de l'argent sur la fraude ? | Non. Le supplément lié au risque va au fonds d'assurance, pas en revenu, et rien n'est prélevé sur l'argent saisi et restitué aux victimes. |
| Quel taux ? | Pas encore fixé : il dépend du trafic réel, et on n'annonce pas de chiffre non mesuré. |

## Version finale (3 min)

Garder les slides 1, 3, 4, 5, 6. Démo réduite au scénario B seul (0:50). Supprimer 2 (fondue
dans l'accroche), 7 et 8 (une phrase de limites en conclusion).
