# OPEN_ANSWERS.md — décisions tranchées en équipe

Ce fichier regroupe les questions de `docs/OPEN_QUESTIONS.md` qui ont reçu une **décision
actée** (marquée « DÉCISION », avec une date et un auteur). Les textes ci-dessous sont la
**source unique** de chaque décision : une fois actée, le texte complet est **déplacé ici** et
`OPEN_QUESTIONS.md` ne garde qu'un **renvoi** vers la section correspondante, plus les questions
et conséquences encore ouvertes.

Règles :

- On n'ajoute ici que ce qui est marqué **DÉCISION** dans `OPEN_QUESTIONS.md`. Une proposition
  « par défaut, à confirmer » (ex. §8 `BEDROCK_MODEL_ID`) reste dans les questions.
- Le statut est recopié tel quel (ex. « à relire par l'équipe ») : on ne le renforce pas.
- Le texte complet d'une décision vit **ici seulement** ; `OPEN_QUESTIONS.md` pointe dessus par un
  renvoi. Toute modification d'une décision se fait donc dans ce fichier (et le renvoi côté
  questions est ajusté s'il change de sens).

## Index

| § | Question tranchée | Date | Par | Statut | Source |
|---|-------------------|------|-----|--------|--------|
| 0 | Décision structurante : où vit la sécurité, et cœur du projet | 2026-10-10 | Équipe 20 | Tranché en équipe | — |
| 0bis | Le Token Ghost s'applique-t-il au seul mint ou à tous les transferts ? | 2026-10-10 | Marceau | Tranché | PR #34 |
| 0bis-a | Quelle affirmation porte le Ghost devant le jury : solvabilité ou récupération ? (#37) | 2026-10-10 | Marceau | Tranché | Issue #37 |
| 0bis-b | Que produit le transfert d'un Ghost ? Fenêtre portée par la valeur, tranches d'échéance (#35) | 2026-10-10 | denybs | Validée en session, à relire par l'équipe | Issue #35 |
| 0bis-c | Collatéral libéré par la destruction d'un Ghost adossé : réserve de restitution (#36) | 2026-10-10 | denybs | Validée en session, à relire par l'équipe | Issue #36 |
| 1 | Détection du mint anormal : invariants, seuils, légitime vs malveillant | 2026-10-10 | denybs | Validée en session, à relire par l'équipe | PR #51 |
| 3 | Réponse graduée : retarder ≠ bloquer, machine à états, quorums multisig | 2026-10-10 | Équipe 20 | Tranché en équipe | — |
| 4 | Angle différenciant : anti-contagion (principal) + supervision IA + cadre DORA | 2026-10-10 | Équipe 20 | Tranché en équipe | — |
| 5 | Mesure de performance : délai de détection, taux de faux positifs, baseline et critères de succès | 2026-10-10 | denybs | Validée en session, à relire par l'équipe | — |
| 6 | Données synthétiques : format JSONL, scénarios recadrés, générateur reproductible | 2026-10-10 | EnzoFB06 | Tranché (propriétaire `data/`) | — |
| 9 | Volet 2 : surveillance adaptative, allongement de fenêtre ciblé, contamination par ratio | 2026-10-10 | Marceau | Validée en session, à relire par l'équipe | PR #38 |
| 10 | Lignage d'un swap : `swap-id` sur notre pool, jambe sortante en règlement différé (#43) | 2026-10-10 | denybs | Validée en session, à relire par l'équipe | Issue #43 |
| 10bis | Qui porte le risque : M' protégé / pur / chèque, routeur + Ghost de paiement, restitution sans fonds ni frais (#84) | 2026-10-10 | Marceau | Validée en session, à relire par l'équipe | Issue #84 |
| 11 | Contamination posée après coup : recalcul hors chaîne + racine de Merkle contestable (#85) | 2026-10-11 | denybs | Validée en session, à relire par l'équipe | PR #95 |
| 79 | Champs manquants monitor/detection : `request_id` optionnel (fix collision), `is_ghost` et données I1/I5/I6 gardés en contexte jusqu'aux événements du contrat (#79) | 2026-10-11 | denybs | Validée en session, à relire par l'équipe | Issue #79 |
| 14 | Lignage et conversions Ghost : plafonnement du soupçon par `balanceOf` du Ghost lu au semis (option (c)) (#104/#106) | 2026-10-11 | marceaupatu123 | Tranché | PR #132 |

---

## §0. Décision structurante — où vit la sécurité, et cœur du projet

### DÉCISION (2026-10-10, Équipe 20) — sécurité **dans le contrat**, cœur = **pricer le risque** via le Token Ghost à contamination par ratio

**La sécurité vit dans le contrat**, pas seulement autour. La surveillance « autour » arrive trop
tard face à une clé de signature volée (scénario Resolv) : le mint est déjà valide. Les invariants
durs (montant dérivé on-chain, bornes) vivent donc **on-chain** ; la surveillance et le LLM
restent **autour** pour la démo et la conformité DORA.

**Cœur du projet retenu : « pricer le risque ».** Le Token Ghost à **contamination par ratio**
(cf. §9) n'est pas qu'un outil de police (geler/détruire) : le ratio par adresse est un **prix du
risque** continu, publié sur la balise de risque et lisible par les protocoles en aval. On ne se
contente pas de bloquer la fraude on/off, on la **rend visible et chiffrée**, et on laisse le
marché et l'aval réagir à ce prix. C'est l'angle différenciant mis en avant au jury.

#### Réponses aux sous-questions de la §0 d'`OPEN_QUESTIONS.md`

- **Montant dérivé on-chain + signature.** Retenu (volet 1). La signature autorise « traiter la
  demande n°X », pas un montant ; le contrat dérive lui-même le montant du dépôt enregistré
  on-chain. Compatible avec le faux protocole via une structure `MintRequest`.
- **Plafonds.** **Pas de plafond fixe par opération.** À la place, une **baseline adaptative** :
  le système apprend le volume habituel (par jour / demi-journée, selon la date et la période de
  l'année) et déclenche quand le trafic courant s'écarte anormalement de cette normale (ex. ~2×).
  Précisions actées en §9 : **ratios normalisés** (pas de volumes absolus), baseline **médiane +
  MAD** sur fenêtre glissante, et déclencheur = **volume élevé ET dispersion effondrée** (le
  volume seul ne suffit pas, sinon chaque pic légitime déclenche). Au déclenchement : on allonge
  la fenêtre Ghost du périmètre suspect et on attend un audit humain avant de « dégeler ».
- **Perte maximale bornée vs plafonds.** Deux choses distinctes : la baseline/le gel est le
  **mécanisme** ; la perte max bornée est la **garantie qui en découle**, énoncée et **vérifiée
  par tests d'invariants / fuzzing Foundry** (jamais « prouvée »). Le volet 2 affirme **deux**
  bornes testables : **perte max bornée** (côté attaquant) ET **friction max bornée** (côté
  défense) — cf. §9.
- **Qui gèle / qui lève (veto asymétrique).** Trois verbes (cf. §9) : **retarder** (surveillant /
  IA seul, auto-expirant) ; **détruire** et **pause globale** (humains, **multisig**). Agir dans
  le sens sûr est solitaire ; agir dans le sens risqué exige le multisig. Multisig = autorisation
  on-chain « M parmi N » : voler une clé ne suffit plus.
- **Volet 3 (balise de risque + marché).** **Retenu comme cœur**, pas comme option. La balise
  publie le prix du risque (ratio) ; un faux marché de prêt / un marché secondaire price la
  décote. Le volet 1 doit néanmoins exister et compiler en premier (il porte la démo
  « vulnérable vs protégé », scénario A).
- **Nombre et types de surveillants.** Deux suffisent pour la démo : un surveillant **règles** sur
  le mint, un sur les **transferts anormaux**. ML en option (vague 5).
- **Prédiction conforme.** Écartée pour 48 h : **seuils simples** mesurés sur trafic rejoué, plus
  honnêtes et plus rapides à calibrer (règle « aucun chiffre sans mesure »).
- **Ordre de priorité si le temps manque.** Inchangé : **volet 1 → volet 2 → volet 3**. Le volet 1
  (montant dérivé) est non négociable ; le modèle de contamination par ratio est la pièce
  maîtresse de la démo, mais ne se *voit* qu'avec le trafic synthétique du scénario D.

#### Marge sur conversion token ⇄ Ghost (décidée en équipe)

Une **marge est prélevée à la conversion** dans les deux sens (token → Ghost et Ghost → token).

**Limite assumée (à dire au jury, pas à cacher)** : une marge **forfaitaire** sur toutes les
conversions taxe aussi les utilisateurs légitimes et entre en tension avec l'argument « friction
bornée et **locale**, proportionnelle à l'exposition réelle » (§9), ainsi qu'avec l'esprit DORA
(protéger l'écosystème, pas en tirer une rente). Piste de cohérence recommandée, à confirmer :
**indexer la marge sur le ratio de contamination** (convertir un Ghost propre coûte ~0, un Ghost
contaminé coûte plus), et **affecter les montants collectés** à la couverture des destructions /
un fonds d'assurance plutôt qu'au profit. Barème et affectation **à mesurer et acter**.

### Reste ouvert

- Barème exact de la marge, forfaitaire vs indexée sur le ratio, et affectation des montants
  collectés (voir la limite assumée ci-dessus).
- Grandeur affichée comme « risque » : **proportion suspecte** (ratio actuel) vs **probabilité de
  fraude** — à trancher pour le pricing et la balise.
- Tous les seuils (déclenchement, conversion, allongement, alerte) restent **à mesurer** sur le
  trafic synthétique (cf. `docs/CLAIMS.md`).
- Détail des sous-questions renvoyées à §9 (baseline, veto asymétrique) et §0bis (Token Ghost).

---

## §0bis. Pivot « quarantaine liquide / Token Ghost »

### DÉCISION (2026-10-10, Marceau) — le Ghost s'applique à **tous les transferts**

**Tranché : le Token Ghost n'est pas limité au mint. Tout transfert de token produit du Ghost chez
le destinataire, converti 1:1 en vrai token après la fenêtre (ex. 10 min) sans anomalie.**

Exemple de référence : A achète du token M à B → A reçoit du **M-Ghost** → devient du **M** après
10 minutes sans anomalie.

**Objectif visé par ce choix** (différent de l'objectif « anti-mint-frauduleux » initial) :
pouvoir **récupérer / annuler des fonds après coup** (lutte contre le blanchiment), ce qu'un Ghost
limité au mint ne permet pas — une fois le vrai token en circulation, plus rien n'est rattrapable.
Argument complémentaire retenu : un Ghost limité au mint laisserait le **marché Coin/Coin-Ghost
quasi vide** (on ne mint pas en continu), donc pas de marché parallèle observable pour la démo.

**Conséquences assumées, à traiter comme du travail d'ingénierie (ne pas les perdre) :**

1. **Liquidité gelée en continu** : 100 % des usages légitimes subissent la fenêtre de
   quarantaine, et non plus le seul cas rare du mint volé. À mesurer, pas à estimer.
2. **Compatibilité AMM / pools DeFi** : chaque swap produit du Ghost non convertible pendant la
   fenêtre. Il faut déterminer si un pool peut encore fonctionner, et sinon quel traitement
   particulier lui appliquer.
3. **Destruction d'une chaîne de transferts** : annuler un échange suppose de défaire des Ghost
   déjà **fragmentés chez N adresses**. Le problème déjà listé ci-dessus devient le cas normal,
   plus le cas exceptionnel.
4. **Choix de la fenêtre** (10 min proposé) : arbitrage entre capacité de récupération et friction
   subie par les utilisateurs légitimes.

**Option intermédiaire écartée par cette décision** (conservée ici pour mémoire, au cas où les
points 1–3 se révéleraient bloquants à l'implémentation) : ne mettre en Ghost que les **transferts
flaggés** par les surveillants (gros montant, adresse neuve, structuring), en s'appuyant sur la
balise de risque et les signaux de la section 2.

### Reste ouvert

- Conséquences 1 à 4 ci-dessus. La §9 apporte une réponse aux points 2 (pools AMM) et 3
  (destruction d'une chaîne).
- Les trois questions existentielles de la §0bis dans `OPEN_QUESTIONS.md` (conformité DORA du
  transfert de perte, destruction d'un Ghost fragmenté, impact sur la liquidité).
- ~~#35 : que produit le transfert d'un Token Ghost (Ghost d'un Ghost) ?~~
  → Tranché, voir §0bis-b ci-dessous.
- ~~#36 : que devient le collatéral quand on brûle un Ghost adossé (collatéral orphelin) ?~~
  → Tranché, voir §0bis-c ci-dessous.
- ~~#37 : aligner `CLAIMS.md` sur l'objectif de la décision (solvabilité ou récupération).~~
  → Tranché, voir ci-dessous.

### DÉCISION (2026-10-10, Marceau) — deux affirmations distinctes, solvabilité en tête (#37)

**Tranché : la ligne unique de `CLAIMS.md` sur le Ghost est scindée en deux affirmations, chacune
avec sa propre méthode de vérification.**

1. **Solvabilité (affirmation principale devant le jury).** Un mint frauduleux détecté avant la
   fin de la fenêtre Ghost ne produit aucun vrai token non adossé (`supply <= collateral`).
   Vérifiée par tests d'invariants Foundry et rejeu des scénarios A/D.
2. **Récupération (affirmation secondaire).** Un transfert suspect est annulable tant que son
   Ghost n'est pas converti, y compris après fragmentation. Vérifiée par rejeu d'une chaîne de
   transferts et mesure de la part récupérée.

**Raisons :**

- Les deux restent vraies avec le Ghost sur tous les transferts : brûler un Ghost adossé donne
  `supply < collateral`, ce qui reste solvable si l'invariant s'écrit `<=`. Le Ghost conserve la
  solvabilité et ajoute la récupération ; elles ne se démontrent pas de la même façon.
- La solvabilité est mise en tête parce qu'elle se vérifie seule (invariants) et ne dépend
  d'aucune question ouverte. La récupération dépend de #36 (collatéral orphelin) et d'un
  arbitrage humain (annuler un transfert = confisquer puis redistribuer, §3).

**Corrections apportées à l'ancienne ligne :**

- « 100 % solvable » retiré : la garantie est **conditionnelle** au fait que la détection soit
  plus rapide que la fenêtre Ghost (cf. `OPEN_QUESTIONS.md` §2, priorité haute).
- « contourne le Volet 1 (quarantaine liquide / Token Ghost) » corrigé : le volet 1 est la
  dérivation du montant depuis le dépôt ; le Ghost est un renfort, pas le volet 1.

**Reste ouvert :** #36 (sort du collatéral libéré) conditionne la colonne « limites » de
l'affirmation de récupération. → Tranché en §0bis-c ci-dessous.

### DÉCISION §0bis-b (2026-10-10, denybs) — la fenêtre est portée par la valeur, pas par le transfert (#35)

_Validée en session, à relire par l'équipe._

**Tranché : il n'existe qu'un seul Ghost par token (M-Ghost), jamais de « Ghost d'un Ghost ». La
fenêtre court depuis l'entrée de la valeur dans le Ghost et ne redémarre pas quand le Ghost
circule.**

- Transfert de **vrai M** : le destinataire reçoit du M-Ghost avec une échéance neuve
  (`maintenant + W`, W = fenêtre normale, §0bis).
- Transfert de **M-Ghost** : le destinataire reçoit du M-Ghost qui **garde son échéance
  d'origine**. Le transfert transmet le Ghost, il n'en crée pas. « Tout transfert produit du Ghost
  chez le destinataire » reste vrai : le destinataire reçoit toujours du Ghost.
- La conversion Ghost → M reste explicite, avec la marge de la §0.

C'est l'option (b) de l'issue #35. Les deux autres sont écartées :

- **(a) Fenêtre remise à zéro à chaque transfert** : un token qui circule ne mature jamais. Et
  c'est une faille : n'importe qui peut envoyer 1 wei de Ghost à une adresse pour repousser
  l'échéance de tout son solde, autant de fois qu'il veut.
- **(c) Transferts de Ghost interdits** : contredit « librement échangeable » et supprime le
  marché secondaire (§0bis, scénario D, §4).

#### Mise en œuvre : des tranches d'échéance bornées par adresse

Deux façons simples de stocker l'échéance d'un solde ont des failles :

- **Échéance moyenne pondérée** (le même calcul que le ratio de la §9) : faille de mélange. Une
  adresse qui détient 1 000 Ghost presque mûrs et reçoit 100 Ghost frais suspects obtient une
  échéance moyenne presque immédiate. Les 100 suspects se convertissent avant la fin de leur
  propre fenêtre, et la détection perd le temps que la §5 lui garantit.
- **Échéance maximale** (la plus tardive gagne) : faille de poussière. Envoyer un peu de Ghost
  frais à une adresse bloque tout son solde ; répété toutes les W minutes, ça le gèle
  indéfiniment.

**Retenu :** chaque adresse range son solde Ghost en **N tranches d'échéance**. La fenêtre W est
découpée en N créneaux fixes, et l'échéance est arrondie au créneau supérieur (le sens sûr).

- Seules les tranches **échues** sont convertibles.
- À l'envoi, les tranches **les plus anciennes partent en premier** : le destinataire reçoit
  l'argent le plus proche de la maturité, le Ghost frais reste chez l'expéditeur.
- Le coût par transfert est borné par N, quel que soit le nombre de transferts passés. Ce n'est
  pas le FIFO par lots écarté en §9, dont le coût croît avec le nombre de transferts.
- N est petit et fixe (proposition : des créneaux d'une minute), à ajuster selon le gas mesuré.

Propriétés, à vérifier par tests d'invariants dans #8 :

- **Aucune valeur ne devient convertible avant W après son entrée dans le Ghost** : le total
  convertible à l'instant T est au plus le Ghost entré avant T − W.
- La poussière ne retarde que la poussière ; mélanger des soldes ne raccourcit aucune échéance.

#### Articulation avec les décisions existantes

- **Ratio de contamination (§9)** : il reste **par adresse** et indépendant des tranches. La
  tranche dit **quand** une valeur peut se convertir, le ratio dit **quelle part** est suspecte.
- **Conversion autorisée si** la tranche est échue **et** l'adresse n'est pas en fenêtre allongée
  (§3) **et** le ratio et le montant absolu suspect sont sous les seuils (§9).
- **Délai de détection (§5)** : la fenêtre ne redémarre pas au fil des sauts. La marge avant
  conversion se mesure donc depuis l'entrée de la valeur (`t0`), quel que soit le nombre de
  transferts de l'attaquant.

#### Conséquences

- **#8** : le contrat Ghost implémente les tranches et teste les deux propriétés ci-dessus.
- **`docs/CONTRACTS.md`** (zone sensible, non modifié) : `GhostTokenMintEvent` /
  `GhostTokenRedemptionEvent` devront porter l'échéance (ou le créneau). Proposition à faire
  valider par le propriétaire de `shared/`.

### DÉCISION §0bis-c (2026-10-10, denybs) — le collatéral libéré va dans une réserve de restitution (#36)

_Validée en session, à relire par l'équipe._

**Tranché : l'invariant s'écrit `valeur(supply M + supply M-Ghost) ≤ collatéral` (cohérent avec
§0bis-a). La différence est une réserve de restitution cantonnée : ni profit du protocole, ni
redistribution automatique.**

- Brûler un Ghost **non adossé** (une fraude qui a contourné le volet 1) réduit le déficit. Brûler
  un Ghost **adossé** (de la valeur légitime volée puis transférée) crée un excédent. Le contrat
  n'a pas besoin de savoir dans quel cas il se trouve : **réserve = collatéral − valeur(supply)**,
  calculée et jamais négative tant que l'invariant tient.
- **Restituer à une victime identifiée** est une décision **multisig 2/3**, distincte de la
  destruction (même quorum, §3). Le montant restitué est **plafonné par la réserve**, donc une
  restitution ne peut pas casser la solvabilité.
- Ce qui n'est pas réclamé après un délai (à fixer) part au **fonds d'assurance**, la même
  affectation que celle recommandée pour la marge de conversion (§0, à confirmer).

Options écartées :

- **Restitution automatique à la victime** : le contrat ne sait pas qui est la victime. Le ratio
  dit quelle proportion d'un solde est suspecte, pas à qui elle a été prise (§9, limites).
  Identifier la victime est une enquête, donc une décision humaine. C'est cohérent avec la
  distinction de l'issue #36 : annuler un mint corrige une émission, annuler un transfert est une
  confiscation suivie d'une redistribution.
- **Excédent conservé par le protocole** : incitation à détruire, contraire à l'esprit DORA (§4).

Effet sur la perte maximale bornée (volet 2) : le protocole ne perd rien (`supply ≤ collatéral`).
Les porteurs de bonne foi perdent `ratio × solde Ghost non converti` (§9). Cette perte est en
partie compensable par la réserve, jamais au-delà.

#### Conséquences

- **#8** : la destruction met à jour l'invariant en `≤` ; ajouter `reserve()` en lecture et une
  restitution multisig 2/3 plafonnée par la réserve, avec tests d'invariants.
- **`docs/CLAIMS.md`** : la colonne « limites » de l'affirmation de récupération (§0bis-a) peut
  maintenant être remplie. Proposition au propriétaire de `docs/`, fichier non modifié.

---

## §1. Détection du mint anormal

### DÉCISION (2026-10-10, denybs) — _validée en session, à relire par l'équipe_

**Le surveillant de mint ne cherche pas des mints « trop gros » : il vérifie, indépendamment du
contrat, que les hypothèses du volet 1 tiennent.**

Raisonnement. Avec le volet 1 (§0), la signature autorise « traiter la demande n°X » et le
contrat dérive lui-même le montant du dépôt. Un mint cohérent avec son dépôt (1:1, aux frais
près) ne rapporte rien à l'attaquant : ce n'est pas une attaque, quelle que soit sa taille. Des
seuils sur la taille d'un mint individuel seraient donc **redondants** avec le volet 1 et ne
produiraient que des faux positifs (une baleine qui dépose 80M et reçoit 80M est légitime).

Référence Resolv (22 mars 2026) : ~200 000 USDC déposés, 80M USR mintés en deux appels à
`completeSwap()` avec une clé `SERVICE_ROLE` compromise, signatures toutes valides (ratio ~400×).
C'est exactement ce que I1 ci-dessous rend impossible on-chain. Sources :
[post-mortem Resolv](https://resolv.xyz/blog/resolv-postmortem-march-22-2026-incident),
[CertiK](https://www.certik.com/blog/resolv-protocol-incident-analysis).

Ce qui reste à surveiller, ce sont les cas où **une hypothèse du volet 1 tombe** :

1. **Le contrat n'est plus celui qu'on croit** : upgrade via une clé admin volée, nouveau rôle de
   mint. `CLAIMS.md` suppose « clés d'administration non compromises » ; le surveillant, hors
   chaîne, ne dépend pas de cette clé.
2. **Le taux est faux** : oracle manipulé (ex. flash loan). I1 est respecté, mais avec un mauvais
   taux.
3. **Le code a un bug** : on dit « vérifié par tests », jamais « prouvé ».
4. **Le destinataire est détourné** : un mint à 1:1 peut quand même être un vol si l'attaquant
   traite la demande d'une victime et envoie les tokens chez lui. Le bilan global reste à 1:1,
   mais l'argent change de poche.

#### Q1 — Invariants du système de mint

| # | Invariant | Appliqué par | Ce qu'il bloque |
|---|-----------|--------------|-----------------|
| I1 | `minted(X) = deposit(X) × taux`, à ε près (frais) | contrat (#5), testé par fuzzing (#6) | Mint gonflé (cas Resolv) |
| I2 | La demande X existe, est en attente, n'est traitée qu'une fois | contrat (#5) | Rejeu, demande fabriquée |
| I3 | Le destinataire du mint X est le déposant de X | contrat (#5) | Détournement à 1:1 |
| I4 | Une seule fonction, un seul rôle peut minter | contrat (#5) | Chemin de mint parallèle |
| I5 | `Δ totalSupply = Σ Mint − Σ Burn` | surveillant (#11) | Mint passé par un chemin non prévu |
| I6 | `totalSupply ≤ valeur du collatéral × facteur` | surveillant (#11) | Dérive de solvabilité (dépend de l'oracle) |

I3 est **nouveau** et doit être appliqué par le contrat : sans lui, le volet 1 laisse passer un vol
à 1:1. Le surveillant recalcule aussi I1 hors chaîne, comme **alarme** (il ne peut plus être violé
on-chain sauf si une hypothèse est tombée).

#### Q2 — Seuils d'anomalie

- **Pas de seuil sur la taille d'un mint individuel** (absolu, relatif à la médiane, z-score) :
  redondant avec le volet 1.
- **Volumes agrégés anormaux** : déjà couverts par la baseline adaptative de la §9 (ratios
  normalisés, médiane + MAD, volume élevé ET dispersion effondrée). Pas de second mécanisme.
- Le surveillant de mint lève une `Alert` sur :
  - toute violation recalculée de I1, I5 ou I6 (tolérance = ε des frais, rien d'autre) ;
  - tout événement d'administration (`Upgraded`, `RoleGranted`, changement d'oracle ou de taux)
    non annoncé au préalable ;
  - un écart du taux / de l'oracle au-delà de δ par rapport à une source de référence.
- Réponse : conforme à la §3. Le surveillant ne peut que **retarder** le périmètre concerné ;
  détruire ou mettre en pause globale reste au multisig. Une violation d'invariant détectée hors
  chaîne signifie que le contrat a été contourné : c'est le cas qui justifie l'audit humain.

#### Q3 — Distinguer un mint légitime important d'un mint malveillant

- Sous le volet 1, un mint **cohérent avec son dépôt et son déposant** (I1 + I3) est légitime par
  définition, **quelle que soit sa taille**. La taille n'est pas un critère.
- La question devient : le mint est-il passé par **le chemin prévu**, avec **le bon taux**, vers
  **le bon destinataire** ? C'est ce que vérifient les invariants et les événements admin.
- Le comportement **après** le mint (sortie rapide, concentration vers peu d'adresses) n'est pas
  traité ici : le Ghost s'appliquant à tous les transferts (§0bis), c'est la contamination par
  ratio et le discriminant de dispersion de la §9 qui le couvrent.

#### Conséquences (à reporter, sans les trancher ici)

- **#11** : `check_mint()` vérifie I1, I5, I6, les événements admin et l'écart d'oracle. Pas de
  seuil de taille.
- **#5** : le contrat protégé doit appliquer I3 (destinataire lié au déposant).
- **#9** (monitor) : écouter aussi les événements d'administration, pas seulement les mints.
- **#2** (`docs/CONTRACTS.md`, zone sensible) : `MintEvent` / `MintRequest` devront porter au
  minimum l'identifiant de demande, le déposant, le destinataire, le montant déposé et le taux.
  Proposition à discuter en équipe, fichier non modifié.
- **#49** : le scénario B de `data/README.md` (« l'attaquant reste sous les plafonds ») n'a plus
  de sens avec le volet 1 et sans plafond fixe ; il est à reformuler autour d'une hypothèse qui
  tombe.

### Reste ouvert

- Relecture par l'équipe.
- Valeurs de ε (frais) et δ (écart d'oracle), et choix de la source de référence du taux, **à
  mesurer**.
- Le contrat est-il **upgradable** ? S'il ne l'est pas, le risque n°1 (clé admin) disparaît en
  grande partie, au prix de ne pas pouvoir corriger un bug.
- Liste exacte des événements d'administration à surveiller.

---

## §3. Réponse graduée — automatique vs validation humaine

### DÉCISION (2026-10-10, Équipe 20) — _tranché en équipe_

Complète la §9 (trois verbes : retarder / détruire / pause globale) en tranchant les points
laissés ouverts : vocabulaire, durées, ce qui est permis pendant un retard, quorums multisig, et
la **machine à états** d'un périmètre. C'est la base directe de `response/orchestrator.py` et du
modèle `ResponseAction` (`shared/`, `docs/CONTRACTS.md`).

#### Vocabulaire — « retarder » n'est pas « bloquer »

L'IA / un surveillant ne **bloque** jamais et ne met jamais en **pause** : elle **retarde**
(allonge la fenêtre Ghost d'un périmètre), de façon **locale** et **auto-expirante**. La
formulation historique « l'IA ne décide jamais seule d'un blocage » (CLAUDE.md,
`response/orchestrator.py`) doit se lire : **l'IA ne décide jamais seule d'une destruction ni
d'une pause globale**. Ce glissement de vocabulaire est acté ici pour lever toute contradiction
apparente dans le code et la doc.

#### Qui décide quoi (rappel §9, pour mémoire)

- **Retarder** (allonger la fenêtre d'un périmètre) : surveillant / IA, **seul** ; **expire tout
  seul**.
- **Détruire** le Ghost suspect d'un périmètre : humains, **multisig** ; irréversible.
- **Pause globale** du protocole : humains, **multisig** ; réversible, coûteuse, dernier recours.

#### 1. Durée et facteur d'allongement

- Facteur d'allongement **fixe et modeste** (proposition de référence : fenêtre normale 10 min →
  fenêtre allongée 1 h). Pas d'allongement adaptatif pour l'instant.
- Expiration liée à **`block.timestamp`** (durée réelle), **pas** à un nombre de blocs : plus
  lisible en démo sur Fuji, où le temps de bloc varie.
- Les valeurs exactes restent **à mesurer** sur le trafic synthétique (règle `docs/CLAIMS.md` :
  aucun chiffre inventé).

#### 2. Ce qui est permis pendant un retard (point clé)

Pendant une fenêtre allongée, sur le périmètre suspect :

- **La circulation reste autorisée** : les Ghost suspects peuvent encore être **transférés**. Le
  modèle de contamination par ratio (§9) garantit que disperser **ne nettoie pas** (soupçon
  conservé) ; inutile donc de geler la circulation.
- **La conversion Ghost → vrai token est suspendue** tant que la fenêtre est allongée. On ne gèle
  pas les fonds, on **retarde seulement la sortie** vers le vrai token.

→ friction minimale et **locale** : on ne bloque personne, on retarde une conversion sur un
périmètre ciblé.

#### 3. Audit humain : opportunité, pas obligation bloquante

- L'allongement ouvre une **fenêtre d'opportunité** pour un audit humain ; il n'exige aucune
  action pour être « défait ».
- **Silence = retour automatique à la normale** à l'expiration. Le biais par défaut favorise donc
  **l'utilisateur légitime**, pas l'attaquant (bon biais pour les faux positifs).
- L'audit peut escalader vers **détruire** ou **pause globale** (voir quorums ci-dessous).

#### 4. Quorums multisig

- **Détruire** le Ghost suspect d'un périmètre : **2 sur 3** guardians.
- **Pause globale** (dernier recours, fort impact) : **unanimité 3 sur 3**.
- **Lever** une pause globale : **même multisig** que pour la décréter. Aucun acteur seul ne peut
  accélérer, libérer ou raccourcir (veto asymétrique respecté).
- Implémentation hackathon : multisig **simulé** on-chain (`mapping(address => bool) guardians` +
  compteur d'approbations), présenté honnêtement comme simulé — pas de Gnosis Safe.

#### 5. Machine à états d'un périmètre (base de l'orchestrateur)

```
          volume élevé ET dispersion effondrée (§9)
NORMAL ───────────────────────────────────────────────► RETARDÉ (fenêtre allongée)
  ▲                                                         │
  │  expiration (silence) : retour auto                     │  audit humain
  └─────────────────────────────────────────────────────── ┤
                                                            ├─► DÉTRUIT        (multisig 2/3, irréversible)
                                                            └─► PAUSE_GLOBALE  (multisig 3/3, réversible via multisig)
```

- `NORMAL → RETARDÉ` : décidé par surveillant / IA, seul (direction sûre).
- `RETARDÉ → NORMAL` : **automatique** à l'expiration (aucune action humaine requise).
- `RETARDÉ → DÉTRUIT` : multisig 2/3 ; détruit `ratio × solde Ghost non converti` (§9).
- `RETARDÉ → PAUSE_GLOBALE` : escalade, multisig 3/3 ; sortie de pause par le même multisig.

### Reste ouvert

- Relecture par l'équipe.
- Valeurs exactes (facteur d'allongement, durées, seuils d'escalade) **à mesurer** sur le trafic
  synthétique.
- Notification de l'audit humain : canal et destinataires (hors périmètre on-chain).
- Alignement du code sur le vocabulaire acté (`response/orchestrator.py`, `CLAUDE.md`) et des
  champs `ResponseAction` dans `docs/CONTRACTS.md` sur cette machine à états.
  → `response/orchestrator.py` **aligné** (PR #56 : machine à états, quorums 2/3 et 3/3, silence
  = retour auto) ; `CLAUDE.md` et le steering alignés (PR steering). Reste `docs/CONTRACTS.md`.

---

## §4. Angle différenciant

### DÉCISION (2026-10-10, Équipe 20) — _tranché en équipe_

On ne retient pas **un** angle isolé : on **hiérarchise** les pistes de la §4 selon ce que la
démo peut *montrer*, et on les présente comme **un angle principal + deux renforts**, unifiés par
une seule thèse. Ce choix est aligné sur §0 (cœur = pricer le risque), §3 et §9 (garde-fous sur
l'IA) : aucune piste n'est jetée, elles sont ordonnées.

#### Thèse unificatrice — **le risque comme signal continu (« pricer le risque »)**

Le ratio de contamination (§9) n'est pas qu'un outil de police (geler / détruire) : c'est un
**prix du risque** par adresse, publié sur la **balise de risque** et lisible par l'aval. On ne
bloque pas la fraude en on/off, on la **rend visible et chiffrée** et on laisse le marché et les
protocoles en aval réagir. Cette thèse chapeaute les trois angles ci-dessous.

#### Angle principal — **Protection des protocoles en aval (anti-contagion)**

- **Pourquoi principal** : c'est le seul angle **démontrable** dans la démo (scénario C :
  mauvaises créances d'un faux marché de prêt **avec vs sans** lecture de la balise de risque).
- **Mécanisme** : déjà bâti en §0 — la balise publie le ratio ; l'aval décote ou refuse un Ghost
  au-dessus d'un seuil. La contagion est **endiguée au lieu d'être propagée**.

#### Renfort A — **Supervision de l'agent de réponse (garde-fou sur l'IA)**

- Déjà acté en §3 / §9 : l'IA ne fait que **retarder** (jamais détruire ni pauser), tout est
  **auto-expirant**, et un **budget de quarantaine** borne la friction (« même notre surveillance
  ne peut geler plus de X % de l'offre »), **friction max bornée testée par fuzzing**.
- **Pourquoi fort** : répond au reproche n°1 fait aux systèmes « IA qui décide ». Maturité visible
  sans code supplémentaire.

#### Renfort B / cadre — **Conformité DORA**

- Utilisé comme **cadre réglementaire qui chapeaute**, pas comme angle technique isolé (il n'y a
  pas de « prestataire tiers » dans la maquette : l'invoquer tel quel serait plaqué).
- Matérialisé par le **journal d'audit** et le **rapport d'incident LLM**, et par le fait qu'on
  protège **l'écosystème** (pas seulement l'émetteur).

#### Tension assumée (à dire au jury, pas à cacher)

Le pivot Token Ghost **transfère** une partie de la perte vers un marché secondaire, ce qui est en
tension avec l'esprit DORA (protéger tout l'écosystème). Réponse retenue : le modèle de
contamination par ratio **ne punit pas l'écosystème en bloc**, il **cible proportionnellement**
l'exposition réelle de chaque adresse — ce qui **limite** la contagion plutôt que de la propager.

### Reste ouvert

- Relecture par l'équipe.
- `#?` : angle DORA « prestataire tiers critique » — à garder comme narratif seulement, sauf si
  l'équipe décide d'introduire un prestataire fictif dans la maquette.
- Mesure du scénario C (mauvaises créances avec vs sans balise) : chiffres **à mesurer**, pas à
  inventer (cf. `docs/CLAIMS.md`).

---

## §5. Mesure de performance

### DÉCISION (2026-10-10, denybs) — _validée en session, à relire par l'équipe_

**Le temps de référence n'est pas une latence absolue, c'est la fenêtre Ghost normale (§0bis).**
Tout se mesure par rapport à elle : une alerte qui arrive après la conversion des Ghost en vrai
token (fin de fenêtre) est inutile, même si elle est « rapide » dans l'absolu. La §5 répond donc
aux trois questions de `OPEN_QUESTIONS.md` en gardant ce fil : détecter **avant conversion**.

Alignement : chaque métrique ci-dessous correspond à une ligne de `docs/CLAIMS.md` (règle « aucun
chiffre affiché sans mesure »). Toutes les cases chiffrées restent **vides tant que non mesurées**.

#### Q1 — Délai de détection

On découpe le trajet « événement on-chain → périmètre retardé » en segments horodatés séparément,
pour savoir **où** le temps part et le présenter honnêtement :

```
t0  événement on-chain (bloc)
│   — latence d'observation —►   monitor voit l'événement
t1  événement reçu par monitor
│   — latence de décision ──►    detection calcule et lève l'Alert
t2  Alert émise
│   — latence de réponse ───►    response retarde le périmètre (allonge la fenêtre)
t3  périmètre retardé
```

- **Délai de détection = `t2 − t0`.** C'est la métrique brute de la §5.
- **Marge avant conversion = `fenêtre_Ghost − (t3 − t0)`.** C'est le chiffre à montrer au jury :
  « quand on retarde, il reste X minutes avant que les fonds suspects deviennent du vrai token ».
  Un délai est un **succès** seulement si cette marge est positive.
- **Statistique** : rejouer un scénario N fois, rapporter **médiane et p95** (pas la moyenne,
  sensible aux pics). Horodatage sur **`block.timestamp`** (cohérent avec §3), pour une mesure
  reproductible et indépendante de l'horloge machine.
- **Honnêteté Fuji** : le temps de bloc varie ; on sépare « délai en temps réel » et « délai en
  nombre de blocs ». On démontre le **mécanisme**, pas une latence de production.

#### Q2 — Taux de faux positifs

- **Jeu de données** : le **trafic normal synthétique sans aucune attaque** (générateur `data/`,
  @EnzoFB06, #24). C'est le dénominateur ; les scénarios d'attaque (A, B reformulé #49, D) servent
  aux vrais positifs, pas aux faux.
- **Unité de mesure** : une **fenêtre d'agrégation** (la durée sur laquelle le détecteur cumule le
  trafic avant de décider). Sa valeur est **à mesurer** et porte une **contrainte dure** : elle
  doit être **strictement plus courte que la fenêtre Ghost normale**, sinon l'alerte arrive après
  la conversion et la mesure n'a pas de sens. (La proposition « tranche de 5 min » de Yannis en §2
  est **une valeur candidate non actée** ; la décision ici ne fixe pas le chiffre.)
- **Définition** : FP = une fenêtre de trafic normal qui déclenche à tort un allongement (`NORMAL
  → RETARDÉ`, §3). Taux de FP = fenêtres déclenchées à tort / fenêtres normales totales.
- **Second compteur, plus honnête** : la **part de l'offre inutilement retardée**. Un FP qui
  retarde 0,1 % de l'offre n'a pas le coût d'un FP qui en retarde 20 % — ce compteur relie
  directement la claim « friction bornée et locale » de `CLAIMS.md`.
- **Vrais positifs / rappel** : sur les scénarios avec attaque, on mesure si l'attaque est détectée
  **avant conversion**. Un TP qui arrive après la fenêtre compte comme un **échec**, pas un succès.
- **Choix du seuil** : les seuils de déclenchement étant « à mesurer », on **balaie** le seuil et
  on trace FP vs détection-avant-conversion ; on **choisit** un point sur la courbe, on ne le
  devine pas.

#### Q3 — Baseline et critères de succès

**Baseline (le « avant », ce à quoi on se compare)** : le monde sans notre système = **Resolv tel
quel** — mint accepté, aucune alerte, conversion immédiate, perte totale. Référence du hack réel :
~200 000 USDC déposés, 80M USR mintés, dépeg en 17 min
([post-mortem Resolv](https://resolv.xyz/blog/resolv-postmortem-march-22-2026-incident)).

**Critères de succès de la démo, par scénario :**

| Scénario | Métrique | Succès si |
|----------|----------|-----------|
| A — vulnérable vs protégé | montant mintable pour un même dépôt | protégé = 1:1 ; vulnérable = gonflé |
| B reformulé (#49) | marge avant conversion | alerte émise avec marge **positive** (avant fin de fenêtre) |
| trafic normal | taux de FP + part d'offre retardée | mesurés, et faibles au seuil retenu |
| C — contagion | mauvaises créances aval, **avec vs sans** balise | avec < sans |
| D — Token Ghost | perte côté protocole vs côté spéculateurs | protocole ≈ 0, perte reportée au marché secondaire |

**Critère transversal** : chaque ligne de `docs/CLAIMS.md` doit avoir une mesure correspondante
dans un de ces scénarios. Pas de claim sans métrique, pas de métrique sans jeu de données.

#### Conséquences (à reporter, sans les trancher ici)

- **#59 / `data`** (@EnzoFB06) : le générateur doit produire (a) un **timestamp par événement**
  pour mesurer `t0`, et (b) un **jeu de trafic normal sans attaque** servant de dénominateur aux
  FP. Issue dédiée créée (en plus de #24 qui ne couvre que les scénarios A/B avec attaque).
- **`monitor` (#9) / `detection` (#11)** : horodater `t0`, `t1`, `t2` pour isoler chaque segment
  de latence.
- **`dashboard` (#20)** : afficher délai de détection (médiane / p95), marge avant conversion, et
  taux de FP — ce sont les chiffres montrés au jury.
- **Lien `CLAIMS.md`** : les lignes « taux de faux positifs mesuré » et « friction bornée / locale »
  trouvent ici leur protocole de mesure.

### Reste ouvert

- Relecture par l'équipe.
- Valeur de la **fenêtre d'agrégation** (candidate : 5 min, §2) et du **seuil de déclenchement**,
  **à mesurer** sur le trafic synthétique.
- Nombre de rejeux N et choix médiane / p95 à confirmer.
- Dépend du générateur de données (#24) pour exister : sans trafic normal horodaté, aucune de ces
  mesures n'est calculable.

---

## §6. Données synthétiques (voir `data/README.md`)

### DÉCISION (2026-10-10, EnzoFB06 — propriétaire `data/`) — _tranché_

Les données alimentent la détection (§1, §9), les mesures de performance (§5) et la démo des
angles (§4). Elles sont donc **cadrées par les décisions déjà actées**, pas inventées librement.
Les scénarios A et B d'origine (`data/README.md`) sont **recadrés** car le volet 1 et l'absence de
plafond fixe les ont rendus caducs (issue #49).

#### Q1 — Format des fichiers et schéma des lignes

- **Format : JSONL** (une ligne = un événement JSON). Retenu car : événements **hétérogènes**
  (`MintEvent` ≠ `TransferEvent`) mal servis par un CSV à colonnes vides ; **rejouable** ligne à
  ligne par le `monitor` comme un flux on-chain ; **épouse les modèles Pydantic** de `shared/`
  (une ligne = un `.model_validate_json()`).
- **Le schéma des lignes n'est PAS redéfini ici.** Il **est** celui des modèles figés dans
  `docs/CONTRACTS.md` (PR #53, issue #2) : `MintEvent`, `TransferEvent`, `MintRequest`, `Alert`…
  Le générateur **doit produire du JSONL qui valide contre ces modèles** (Pydantic strict
  `extra="forbid"`). Conséquences directes à respecter :
  - montants en **entiers base units** (jamais de float) ;
  - timestamps **UTC ISO 8601** ;
  - adresses / hash au **format EVM** validé par regex ;
  - `MintEvent.request_id` corrèle avec `MintRequest.request_id` ; le montant du mint est **dérivé
    on-chain**, pas choisi.
- **Dashboard** : pas de second format. Le JSONL se lit en DataFrame
  (`pd.read_json(path, lines=True)`).

#### Q2 — Scénarios recadrés

Un **flux de trafic normal** horodaté sous-tend tous les scénarios : volume par **créneaux de
5 min** (§2/§5), nombreuses adresses, saisonnalité par créneau. C'est la base de calibration de la
baseline **médiane + MAD** (§9) et la seule façon de mesurer le **taux de faux positifs** (§5).
C'est le gros du travail, avant les attaques.

| Scénario | Démontre | Mécanisme | Statut |
|----------|----------|-----------|--------|
| **A — mint gonflé (Resolv rejoué)** | volet 1 | demande n°X dont le mint tenté ≫ dépôt (ratio type ~400×) ; contrat vulnérable accepte, protégé bloque (I1) | recadré : montant incohérent, pas « gros » |
| **B — hypothèse du volet 1 qui tombe** | surveillant hors chaîne | **détournement à 1:1** (I3) : la demande d'une victime est traitée vers l'adresse de l'attaquant ; bilan global 1:1, mais l'argent change de poche. Variante : événement admin non annoncé (upgrade/clé volée) | reformulé (ferme #49) |
| **C — contagion** | angle principal §4 | gel publié sur la balise ; mauvaises créances d'un faux marché de prêt **avec vs sans** lecture de la balise | inchangé |
| **D — marché secondaire du Ghost** | §0bis / §9 | Ghost fragmenté sur N adresses ; contamination par ratio ; destruction proportionnelle au gel confirmé | inchangé |

Tous les **chiffres** (volumes, nombre d'adresses, timings, ratios) sont **à mesurer / calibrer**,
jamais inventés (`docs/CLAIMS.md`).

#### Q3 — Outil de génération et commande

- Script Python **`data/generate.py`**, lançable par `python -m data.generate --scenario <A|B|C|D>
  --seed <n>` et exposé par une cible **`make data`**.
- **Graine aléatoire fixe** par défaut → reproductibilité (exigée par `CLAIMS.md`).
- Le script **importe les modèles de `shared/`** et sérialise via Pydantic : garantit que le JSONL
  produit reste valide si le schéma évolue (une seule source de vérité, pas de schéma dupliqué).
- Sortie dans `data/` (ex. `data/normal.jsonl`, `data/scenario_a.jsonl`, …), **non commitée** si
  volumineuse (à régler dans `.gitignore` avec l'équipe).

### Reste ouvert

- Relecture par l'équipe.
- Valeurs exactes (volumes par créneau, saisonnalité, N adresses, ratios d'attaque), **à mesurer**.
- Liste fixe des adresses « point de sortie » (exchange/bridge) à produire — cf. §2, à coordonner.
- Faut-il committer les JSONL générés ou seulement le générateur + la graine ? (taille vs
  reproductibilité). À trancher avec l'équipe et `.gitignore`.
- Variante retenue pour B (détournement 1:1 vs événement admin) pour la démo principale.
  Seul le détournement 1:1 est généré (PR #57) : l'événement admin n'a pas de modèle dans
  `shared/`.
- Implémentation (PR #57) : `--scenario <normal|A|B|all>` ; C et D pas encore générés (#25,
  dépendent de #7 / #8). Sorties dans `data/generated/`, pas encore dans `.gitignore`.

---

## §9. Volet 2 — surveillance adaptative, allongement de fenêtre ciblé et modèle de contamination par ratio

### DÉCISION (2026-10-10, Marceau) — _validée en session, à relire par l'équipe_

Le volet 2 n'est **pas** une garantie statique seule : c'est une **deuxième sécurité réactive**
posée au-dessus du Token Ghost permanent (fenêtre normale courte, ex. 10 min, sur tous les
transferts — cf. §0bis).

#### Principe

Quand le trafic du jour est jugé anormal, on **allonge la fenêtre Ghost** du périmètre suspect, on
**publie une alerte sur la balise de risque** (lecture par les protocoles DeFi en aval, volet 3),
et on **attend un audit humain**. L'allongement est **auto-expirant** : si l'humain ne confirme
rien, la fenêtre revient d'elle-même à la normale. Aucune action humaine n'est requise pour
« défaire » une fausse alerte.

#### Trois verbes distincts (lève la contradiction « l'IA ne décide jamais seule » vs « tout surveillant peut geler »)

| Action | Qui décide | Réversibilité |
| ------ | ---------- | ------------- |
| **Retarder** (allonger la fenêtre d'un périmètre) | surveillant / IA, seul | **expire tout seul** |
| **Détruire** le Ghost suspect d'un périmètre | humains, **multisig** | irréversible |
| **Pause globale** du protocole | humains, **multisig** | réversible, coûteuse, dernier recours |

L'IA ne « bloque » jamais : elle **retarde**, localement, de façon auto-expirante (veto
asymétrique respecté — direction sûre uniquement, jamais raccourcir ni libérer). La formulation
« l'IA ne décide jamais seule d'un blocage » (CLAUDE.md, response/orchestrator.py) doit se lire :
l'IA ne décide jamais seule d'une **destruction** ni d'une **pause globale**.

Exception purement on-chain, sans IA : si un invariant dur est violé (émis > f(collatéral)), le
contrat refuse. C'est le volet 1.

#### Distinguer attaque et croissance légitime (répond à §2)

- **Ratios normalisés**, jamais de volumes absolus : mint/collatéral, volume/offre en circulation.
  La croissance légitime laisse les ratios stables → invisible pour le détecteur.
- **Dispersion** comme discriminant principal : la croissance légitime est **large** (beaucoup
  d'adresses/contreparties, adresses anciennes) ; l'attaque est **concentrée** (peu de
  destinations, adresses neuves, sortie rapide). Déclencheur = **volume élevé ET dispersion
  effondrée**, pas volume élevé seul.
- Baseline **médiane + écart absolu médian (MAD)** sur fenêtre glissante (robuste au bruit qu'un
  attaquant injecterait pour élargir une baseline moyenne/écart-type ; s'adapte seule à la
  croissance progressive).
- Soupape : **reconnaissance de croissance signée en multisig** pour relever la baseline sur un
  événement connu (listing, campagne).

#### Ciblage chirurgical — modèle de contamination par **ratio par adresse**

**Condition** : le ciblage n'est possible que si le Ghost porte sa **provenance**. Sans lignage,
c'est tout-ou-rien (allonger pour tout le monde). Ce lignage est **le même** que celui requis par
#33 (destruction d'une chaîne) → un seul mécanisme, deux usages (retarder ET détruire).

**Mécanisme retenu** (on écarte FIFO/lots : coût gas explosif + manipulable par micro-lots ; et
« le plus suspect gagne » : effet tache d'huile qui marque tout le token) :

> On ne suit pas des pièces. Chaque adresse porte **un seul nombre** : la **fraction suspecte** de
> son solde Ghost (son « ratio de contamination »). À chaque transfert, le montant envoyé porte le
> **ratio courant de l'expéditeur** ; le destinataire met à jour son ratio en **moyenne pondérée
> par les montants**.

Propriétés :

- **Coût constant** par transfert (une multiplication) — indépendant de la profondeur/fragmentation.
  Supprime le problème de limite de gas de #33.
- **Conservation du soupçon** : fractionner et disperser **ne nettoie pas** (la somme des soupçons
  est conservée) → anti-blanchiment par construction.
- **Pas de tache d'huile** : une grosse adresse légitime touchée par une goutte de suspect finit à
  un ratio minuscule → faux positifs limités.
- **Réversible** : audit blanchissant → ratios concernés remis à 0.

#### Réponses aux questions associées (anciennement ouvertes dans #33)

- **Que détruit-on ?** La **fraction suspecte** de chaque adresse (ratio × solde Ghost non
  converti), pas tout le solde. Porteur de bonne foi à 2 % de contamination → perd 2 %.
  Proportionnel à l'exposition réelle.
- **Ghost déjà converti avant le gel ?** Irréversible, et **voulu**. La conversion n'est permise
  que si le ratio (et le **montant absolu suspect**, cf. ci-dessous) est sous seuil au moment de la
  conversion. Un lignage marqué suspect **avant** conversion reste en fenêtre allongée.
- **Gas / profondeur de chaîne ?** Supprimé : plus de chaîne à parcourir, un ratio par adresse mis
  à jour à la volée.
- **Pools AMM ?** Un pool est une adresse avec un ratio ; il se redistribue au retrait de
  liquidité (soupçon conservé). La balise de risque publie le ratio du pool ; l'aval peut le
  refuser en garantie au-dessus d'un seuil. Pool ni figé ni vidé.

#### Garde-fou sur le surveillant lui-même (extension du volet 2)

Pour qu'une IA buguée/compromise ne gèle pas l'économie :

- facteur d'allongement **maximal** par périmètre ;
- **budget de quarantaine** : part maximale de l'offre sous fenêtre allongée à un instant donné ;
  au-delà, extension = humain requis.

→ le volet 2 affirme alors **deux** bornes testables par fuzzing Foundry : **perte max bornée**
ET **friction max bornée** (« même notre surveillance ne peut geler plus de X % de l'offre »).

#### Limites assumées (à dire au jury, pas à cacher)

- Pouvoir annuler des transferts = **pouvoir de clawback** : hypothèse de confiance, pas gratuit.
  « Le protocole peut récupérer des fonds » ⇒ « le protocole peut vous en reprendre ».
- Le ratio dit « quelle **proportion** est suspecte », pas « quelles pièces » — suffisant pour
  geler/détruire/alerter proportionnellement.
- **Auto-contamination défensive** : un attaquant peut se mélanger du légitime pour baisser son
  ratio sous le seuil. Parade : seuils de conversion/allongement dépendant **aussi du montant
  absolu suspect** (conservé, insensible à la dilution), pas seulement du ratio.
- **Tous les seuils** (conversion, allongement, alerte balise, budget de quarantaine) sont **à
  mesurer** sur le trafic synthétique. Aucun chiffre inventé (cf. `docs/CLAIMS.md`).

### Reste ouvert

- Relecture par l'équipe (statut « validée en session, à relire par l'équipe »).
- Valeur de tous les seuils, à mesurer sur le trafic synthétique.
- §2 n'est que **complétée** : définitions d'« adresse neuve » et de « point de sortie », choix
  final des signaux et de leur combinaison (règles, score, ML).
- #35 et #36 ne sont pas abordés par cette décision. → Tranchés en §0bis-b et §0bis-c.
- #33 (détruire une chaîne de Ghost fragmentés) : le mécanisme est choisi et justifié ici
  (contamination par ratio). Les tests d'invariants demandés par #33 (profondeur de chaîne,
  fragmentation large, conservation du soupçon) sont réalisés dans #8.

---

## §10. Lignage transactionnel — reverter les deux jambes d'un échange

### DÉCISION (2026-10-10, denybs) — `swap-id` sur notre pool seulement, jambe sortante en règlement différé (#43)

_Validée en session, à relire par l'équipe._

**Tranché : sur notre pool, un swap ne paie pas l'actif sortant tout de suite. Il crée une créance
liée au swap (`swap-id`), réclamable quand le Ghost vendu arrive à échéance. Si la fraude est
confirmée, les deux jambes sont annulées ensemble.**

Exemple : un attaquant vend du M-Ghost suspect au pool contre de l'USDC.

1. Le pool reçoit le M-Ghost avec son échéance (§0bis-b) et le ratio du vendeur (§9).
2. Le vendeur ne reçoit pas l'USDC : il reçoit une **créance** `swap-id` qui porte le montant, son
   ratio au moment du swap et l'échéance du Ghost vendu.
3. À l'échéance, sans destruction confirmée, le vendeur réclame son USDC.
4. Si une destruction est confirmée (multisig 2/3, §3) : le pool perd la part suspecte du Ghost
   acheté (`ratio × solde`, §9), et la créance du vendeur est annulée à hauteur de
   `ratio × montant`. L'USDC non payé reste dans le pool et compense sa perte. Les deux jambes
   s'annulent pour le pool.

Réponses aux questions de la §10 d'`OPEN_QUESTIONS.md` :

- **Pas de stablecoin pivot, pas de nouveau dépositaire.** L'USDC est déjà dans le pool (c'est sa
  liquidité) ; on retarde seulement son paiement. L'objection faite au token Z ne s'applique pas.
- **DEX tiers** : pas de `swap-id` possible, on ne contrôle pas leur règlement. Limite assumée : un
  pool tiers n'est couvert que par son ratio (une adresse comme une autre, §9) et par la balise de
  risque (§4). L'USDC qu'un DEX tiers a déjà payé à un attaquant n'est pas récupérable.
- **Propagation du soupçon** : le `swap-id` est seulement un **lien de revert**. Le soupçon passe
  par le ratio côté M (§9). La créance garde le ratio du vendeur au moment du swap, uniquement pour
  savoir quelle part annuler.
- **Friction** : le vendeur attend la même fenêtre que n'importe quel détenteur de Ghost (§0bis).
  Aucune friction supplémentaire.

### Reste ouvert

- Relecture par l'équipe.
- Priorité : **vague 5**, après #8 (Ghost) et #7 (balise + marché de prêt), dans le pool simulé du
  scénario D.
- → **Étendu par §10bis** ci-dessous (#84) : règlement différé via un routeur pour toute vente de
  M', paiement en Ghost de l'actif, M' protégé / pur / chèque, restitution aux victimes.

---

## §10bis. Qui porte le risque — protégé, pur, chèque ; restituer, jamais garder

### DÉCISION (2026-10-10, Marceau) — le risque ne porte que sur les acteurs du **M' pur** ; le voleur ne reçoit jamais que du Ghost ; le protocole ne garde rien (#84)

_Validée en session, à relire par l'équipe._

**Problème de départ.** Avec §0bis et §10 seuls, une vente de M-Ghost frauduleux hors de notre pool
paie le voleur en vrai actif tout de suite. Exemple de référence : 10 M frauduleux revendus 10 $ de
main en main jusqu'à 40 personnes. Au gel, seul le 40e détenteur voit ses M' brûlés : **il perd
10 $ et le voleur garde 10 $**. Le protocole est solvable, mais la fraude reste rentable.

**Objectifs de la décision** :

1. empêcher le vol et le blanchiment ;
2. garder un marché de Ghost spéculatif ;
3. faire porter **tout** le risque sur ceux qui achètent et vendent du **M' pur** ;
4. **ne rien financer** avec de l'argent issu d'une fraude, ni avec des frais de protocole.

**Principe : personne ne garde l'argent de personne.** Ce qui est bloqué est soit rendu à son
propriétaire, soit restitué à une victime. Le protocole ne détient jamais rien pour lui-même.

#### 1. Trois statuts de M' (étiquette par tranche d'échéance, §0bis-b)

| Comment on l'a reçu | Statut | En cas de destruction confirmée |
| --- | --- | --- |
| Acheté contre du **vrai M**, via le routeur, avec son paiement bloqué | **protégé** | on récupère **son propre paiement bloqué** |
| Acheté à quelqu'un alors que c'était **encore du M'** | **pur** | on perd sa part (`ratio × solde`, §9) : risque choisi, pricé par la décote, réduit par la restitution (point 4) |
| Reçu **sans paiement on-chain** (don, salaire payé en direct) | **chèque** | le M' n'arrive jamais ; on n'avait rien payé on-chain |

- Revendre un M' (protégé ou chèque) avant l'échéance donne du M' **pur** chez l'acheteur.
- **Chèque** : un paiement en M n'est vraiment encaissé qu'à l'échéance, comme un chèque. S'il est
  annulé, le receveur n'a rien perdu sur la chaîne ; il garde sa créance hors chaîne contre le
  payeur (comme un chèque sans provision). Ce statut **remplace tout fonds de protection**.
- **Anti-blanchiment** : un don ne donne jamais de protection. Un voleur ne peut pas « offrir » son
  M à un complice pour le rendre protégé.
- Coût constant par transfert (une étiquette par tranche).

#### 2. Toute vente passe par un routeur ; le paiement est toujours un Ghost

- Pendant la fenêtre, le M' ne bouge **que via le routeur** (DEX tiers et transfert direct
  refusés). Il suffit de restreindre le M' : avant l'échéance, le voleur ne détient que du M'.
- Ce que paie l'acheteur (USDC, wBTC…) est bloqué dans le **coffre de cet actif**. Le vendeur
  reçoit le **Ghost de cet actif** (USDC-Ghost…), 1:1, converti à l'échéance du M' vendu.
- **Un Ghost par actif, sans oracle** (on rend toujours l'actif bloqué) et **sans prix plancher**
  (la décote reste, donc le marché).
- Le Ghost de paiement suit les mêmes règles : il circule librement, porte un ratio (§9), et un
  USDC-Ghost revendu avant échéance devient lui aussi **pur**.

#### 3. Coffre : deux sorties seulement, aucune vers le protocole

Le coffre ne peut envoyer l'actif bloqué qu'à : **(a)** le porteur du Ghost de paiement à
l'échéance, ou **(b)** une restitution selon la règle du point 4. Aucune autre sortie, ni vers le
protocole, ni vers le multisig. Une clé volée ne permet pas de vider un coffre.

#### 4. À la destruction confirmée (multisig 2/3, §3) : restituer, jamais garder

1. On brûle le M' contaminé (ratio §9) et le Ghost de paiement **des seules adresses graines**
   (`AlertSeed`). Les vendeurs intermédiaires gardent leur paiement.
2. L'argent bloqué derrière le Ghost de paiement du voleur **n'a jamais été à lui** : c'est celui
   de ses acheteurs. Il est restitué **automatiquement**, selon une règle fixe et vérifiable :
   - d'abord aux porteurs dont le M' a été brûlé **dans ce lot**, au prorata du montant brûlé,
     **plafonné par ce qu'ils avaient payé** ;
   - le reste, s'il y en a, à **celui qui avait payé le voleur**.
3. Un porteur protégé récupère son propre paiement bloqué (rien n'est pris à personne d'autre).
4. Le vrai M brûlé dans un cas de blanchiment libère du collatéral : il va à la **réserve de
   restitution** (§0bis-c) pour la victime d'origine, jamais au protocole.
5. Le protocole ne gagne rien à détruire : aucune incitation à détruire (§0bis-c, DORA).

#### 5. Exemples de référence (à rejouer en démo et en tests)

**Cas 1 — achat protégé de vrai M à un blanchisseur.** Tu paies 10 $ (bloqués), tu reçois du M'
protégé, le vendeur reçoit 10 USDC-Ghost. Fraude confirmée : ton M' et son USDC-Ghost sont brûlés,
tes 10 $ te reviennent. Toi 0, vendeur 0. Le collatéral libéré va à la réserve de restitution.

**Cas 2 — chaîne des 40, en M' pur, même prix (10 $).**

| Qui | Résultat |
| --- | --- |
| Voleur (A1) | 0 : son USDC-Ghost est brûlé |
| A2 à A39 | 0 : ils gardent leur paiement |
| A40, dernier porteur de M' pur | M' brûlé, 10 $ restitués : 0 |
| Protocole | 0 : ne touche rien |

**Cas 2bis — mêmes 40, prix qui montent (voleur vend 10 $, A40 achète 15 $).** A40 récupère 10 $
et perd 5 $. Ces 5 $ ont été gagnés par les intermédiaires qui ont revendu plus cher : le risque se
partage entre acheteurs et vendeurs de M' pur, par les prix.

**Cas 3 — salaire payé en M par un voleur, hors routeur.** Le salarié reçoit du M' **chèque**.
Fraude confirmée : le M' est brûlé, le salarié n'a rien payé on-chain ; il garde sa créance hors
chaîne contre l'employeur.

#### 6. Où reste le risque

Uniquement sur les acteurs du M' pur, quand l'argent bloqué du voleur ne couvre pas les pertes :
le voleur a fait circuler sans vendre, a été payé à côté, ou les prix ont monté en route. C'est ce
risque qui justifie la **décote**, donc le marché spéculatif (§0 : pricer le risque).

#### 7. Vol et blanchiment

- Avant l'échéance, le voleur ne détient que du Ghost et n'est payé qu'en Ghost : tout est
  récupérable.
- Chaque transfert de **vrai** M rouvre une fenêtre (§0bis-b) : blanchir par sauts coûte une
  fenêtre par saut, et chaque saut est rattrapable.
- Pour encaisser du vrai actif, le voleur doit attendre l'échéance (donc la détection) ou trouver
  quelqu'un qui le paie à côté (complice ou imprudent).

#### 8. Financement

- **Remboursements** : par le propre paiement bloqué de chacun, ou par restitution aux victimes.
  **Aucun fonds**, aucun argent issu d'une fraude conservé.
- **Fonctionnement** : le gas, payé par les utilisateurs comme pour toute transaction. **Aucun
  frais de protocole.**
- **Conséquence sur §0** : la marge de conversion n'est plus nécessaire au système. À confirmer
  en équipe (modifie la décision §0).

#### 9. Standard, pas service

Interface ouverte + bibliothèque de référence ; **chaque émetteur déploie sa propre instance**
(routeur, coffres, multisig, surveillants, choix des balises). Aucun registre central. Un échange
M' contre N' entre deux tokens du standard : chaque émetteur règle sa jambe. Pour le hackathon :
**une seule chaîne** (Fuji), une instance de référence (M), une seconde (N) si le temps le permet.

#### Options écartées

- **Fonds de protection alimenté par l'argent repris aux voleurs** : cet argent appartient aux
  victimes ; le garder ferait du protocole le détenteur du produit d'une fraude et créerait une
  incitation à détruire.
- **Fonds alimenté par des frais / la marge de conversion** : inutile avec le statut « chèque » et
  la restitution ; écarté pour ne pas financer la protection par des frais.
- **Stablecoin pivot Z permanent** (`OPEN_QUESTIONS.md` §10) : reste écarté. Le Ghost de paiement
  est une créance de la durée de la fenêtre, toujours adossée 1:1 à l'actif bloqué.
- **Z multi-actif avec oracle** : manipulable, et inutile si on rend l'actif bloqué.
- **Multi-chaînes / pont** : les ponts sont la cible la plus attaquée ; hors périmètre hackathon.
- **Prix plancher** contre le paiement à côté : exige un oracle et supprime la décote.
- **Rembourser A40 avec l'argent du dernier détenteur** : fait payer un innocent.
- **Tout rembobiner (chaque acheteur remboursé de son paiement)** : supprime le risque, donc le
  marché du M' pur.
- **Protection pour un M' reçu en don** : porte ouverte au blanchiment par complice.

#### Ce que ça modifie

- **§0** : la marge de conversion n'est plus requise (à confirmer).
- **§0bis / principe de conception** : « la perte est assumée par les acheteurs de Tokens Ghost »
  devient « la perte est assumée par les acteurs du **M' pur** ; le M' acheté contre du vrai M est
  protégé ; le M' reçu sans paiement est un chèque ». À reporter dans `CLAUDE.md`, le steering et
  `docs-site` (propriétaires à prévenir, non modifiés ici).
- **§0bis-c** : la réserve de restitution reçoit aussi le collatéral libéré dans le cas 1.
- **§10** : le règlement différé n'est plus limité à notre pool : routeur pour toute vente de M'.
  « DEX tiers » devient « DEX tiers exclus pendant la fenêtre ».
- **#8** : trois statuts par tranche, M' transférable seulement via le routeur.
- **#65** : le pool simulé devient un cas particulier du routeur (paiement en USDC-Ghost).
- **`docs/CONTRACTS.md`** (zone sensible, non modifié) : les événements Ghost devront porter le
  statut de tranche et l'actif du Ghost de paiement ; un événement de restitution est à ajouter.
  Proposition à faire valider par le propriétaire de `shared/`.

#### Limites assumées (à dire au jury)

- **Détection plus lente que la fenêtre** : après l'échéance, tout est converti. Aucun mécanisme ne
  remplace une alerte à temps.
- **Paiement à côté** (liquide, USDC hors routeur) : invisible pour le contrat ; risque pris par
  celui qui paie, sans aucune garantie de livraison.
- **Fraude sous les seuils**, **faux positifs**, **multisig corrompu** : inchangés (§3, §9).
- **Coffres** : de vrais fonds. Les deux sorties protègent d'une clé volée, pas d'un bug du coffre.
  **Bug de la bibliothèque partagée** : touche tous les émetteurs ; parade = plusieurs
  implémentations, audits, invariants.
- **Pouvoir de reprendre** étendu à l'actif de paiement bloqué : hypothèse de confiance plus lourde.
- **Statut chèque** : le receveur hors routeur n'est pas indemnisé on-chain ; son recours est hors
  chaîne.
- **Réglementation** (MiCA, blocage et restitution de fonds de tiers) : non vérifiée.

### Reste ouvert

- Relecture par l'équipe.
- **Contamination posée après coup** (issue #85, `OPEN_QUESTIONS.md` §11) : **bloque la
  conception**. Piste recommandée pour le hackathon : recalcul hors chaîne + racine de Merkle
  signée par le multisig, contestable par tous.
- Confirmer l'abandon de la marge de conversion (§0).
- Tests d'invariants à écrire dans #84 :
  - aucun vrai actif ne sort du coffre vers un vendeur avant l'échéance ;
  - `coffre(actif) >= somme des Ghost de paiement de cet actif` ;
  - aucune sortie du coffre vers le protocole ou le multisig ;
  - un porteur protégé ne perd jamais rien ;
  - restitution totale ≤ argent bloqué du voleur, et somme des restitutions + paiements = entrées ;
  - rejeu des cas 1, 2, 2bis et 3.
- Friction à **mesurer** (attente de l'actif final, exclusion des protocoles hors standard).

## §79. Champs manquants repérés par monitor/detection (#79)

> Renvoi depuis l'issue #79 (écarts repérés pendant #9/#10/#11). Propriétaire de `shared/` :
> @marceaupatu123.

### DÉCISION (2026-10-11, denybs) — _validée en session, à relire par l'équipe_

Trois écarts avaient été remontés entre `shared/models.py` et les besoins de monitor/detection.
Verdict, un par un :

**1. `MintEvent.request_id` — collision de sentinelle (CORRIGÉ).** C'était le seul **bug** :
un `Transfer` ERC-20 nu ne porte pas l'id de demande, et le monitor mettait la sentinelle
`UNKNOWN_REQUEST_ID = 0`, qui **entre en collision** avec la vraie demande n°0
(`data/generate.py` numérote à partir de 0, `MintRequest.request_id` `ge=0`). **Décision :**
`MintEvent.request_id` devient `int | None` (défaut `None`). `None` = **inconnu**, jamais une
vraie demande ; une demande réelle garde un entier `ge=0`. Le monitor met `None`
(`UNKNOWN_REQUEST_ID = None`). detection ne corrèle pas par ce champ tant qu'il peut être `None`
(c'était déjà le cas). Un événement dédié futur (`Minted` avec id, côté contrat #5) renseignera un
vrai id sans nouveau changement de modèle. Changement **non cassant** (élargissement du domaine) ;
`docs/CONTRACTS.md` (ligne `MintEvent`) mis à jour.

**2. `TransferEvent.is_ghost` — gardé par design, tranché avec #8.** `is_ghost` n'est pas
déductible d'un `Transfer` ERC-20. Le monitor le fixe par **configuration de listener**
(`MONITOR_TOKEN_IS_GHOST`, un listener par contrat : token réel vs Ghost). **Décision :** on ne
touche pas à `shared/` pour l'instant — c'est le **design du contrat Ghost (#8)** qui fixera comment
distinguer un Ghost on-chain (événement dédié, ou contrat Ghost séparé). Jusque-là, la
configuration de listener est la bonne couche : le champ `is_ghost` du modèle reste correct, seule
sa **source** est provisoire.

**3. Données des invariants I1/I5/I6 — gardées en contexte explicite par design.** `MintEvent`
n'a ni montant déposé ni taux (I1) ; aucun modèle partagé ne porte l'offre totale (I5), la valeur
du collatéral (I6), ni les événements d'administration (`Upgraded`, `RoleGranted`, oracle/taux).
detection les reçoit aujourd'hui en **paramètres explicites** (`MintContext`, `AdminEvent`,
`AdminAnnouncement` dans `detection/inputs.py`). **Décision :** on **ne les ajoute pas** à
`shared/` maintenant. Raison : **aucun contrat ne les émet encore** — les mettre dans le modèle
partagé serait inventer une forme avant d'avoir la source on-chain. La vraie source sera les
**événements du contrat protégé (#5)** (`SwapRequested`/`SwapCompleted` portent déjà `depositAmount`
et `rate` ; `RateChanged`, `RoleGranted`… existent). Quand monitor décodera ces événements dédiés,
on fera **une seule** révision de `shared/` alignée sur ce qui est réellement émis, plutôt que
plusieurs champs spéculatifs. Le passage par contexte explicite reste l'interface d'ici là.

### Reste ouvert

- ~~Révision groupée de `shared/` (montant/taux/offre/collatéral/admin) **le jour où monitor décode
  les événements dédiés du contrat #5**, pas avant — à faire par le propriétaire de `shared/`.~~
  → **Faite (#104, 2026-10-11)**. Le monitor décode depuis #116, #128 et #129. Choix de mise en
  œuvre, par Kiro pour @marceaupatu123 (propriétaire de `shared/`), à relire par @denybs et
  @Yannis1307 :
  - `MintEvent` ajoute, en champs optionnels, ce que porte `monitor.protected.MintProvenance` :
    `depositor`, `deposit_amount`, `rate_wad` (valeur brute du contrat, ×10¹⁸),
    `provenance_source` (`request`/`completion`), `claimed_minted`, et `via_protected_path`
    (équivalent de `MintContext.path_unexpected`, I4). `None` = inconnu ; la cohérence des champs
    est validée par le modèle. Changement non cassant.
  - `AdminEvent` partagé, avec des champs typés par type d'événement (`role` en bytes32,
    `old_rate_wad`/`new_rate_wad`) plutôt qu'un dictionnaire libre.
  - `SupplySnapshot` (I5, I6) : la forme est fixée. Le monitor ne le produit pas encore ;
    `CONTRACTS.md` le dit.
  - Le taux reste **brut** (valeur du contrat) : la conversion en base units reste au
    consommateur, pour qu'un seul module (`detection.provenance.rate_from_wad`) la porte.
  - Spécification : `docs/CONTRACTS.md` (`MintEvent`, `AdminEvent`, `SupplySnapshot`).
- ~~Distinction on-chain d'un Ghost (`is_ghost`) : à figer avec le design du contrat Ghost (#8).~~
  → Figée : le Ghost M' est un **contrat séparé** (#8). Un log venant de ce contrat donne
  `is_ghost = true` (#129) ; la description de `TransferEvent.is_ghost` a été mise à jour.

## §11. Contamination posée après coup — comment rattraper le M' déjà propagé (#85)

> Renvoi depuis `OPEN_QUESTIONS.md` §11.

### DÉCISION (2026-10-11, denybs) — _validée en session, à relire par l'équipe_ : piste (b), recalcul hors chaîne + racine de Merkle

**Problème.** Le ratio de contamination (§9) se transmet **au moment** de chaque transfert. Si le
voleur n'est marqué suspect (`AlertSeed`) qu'**après** avoir fait circuler son M', son ratio
valait 0 au moment des ventes : le soupçon n'a pas suivi la chaîne. Comment atteindre le M' chez
le dernier détenteur (ex. le 40e de la chaîne de §10bis) ?

**Mesure qui tranche** (`python -m data.late_marking`, PR #95, inclus dans `make calibrate`,
données **fictives**, chaîne des 40 de §10bis, voleur marqué **après** avoir tout revendu,
détection à 3 min, fenêtre Ghost `W = 10 min`) :

| Piste | M' récupéré |
|---|---|
| (a) lignage d'origine par tranche | **100 %** |
| (b) recalcul rétroactif hors chaîne + preuve | **100 %** (même couverture que (a)) |
| (c) contamination prospective seule | **0 %** |

Lecture de la mesure : **(a) et (b) récupèrent autant** ; le vrai levier n'est **pas** la piste
mais la **vitesse de détection face à l'échéance** — avec lignage (a ou b) on récupère tout tant
que l'alerte **précède l'échéance** du M' (W), et rien au-delà. (c) ne rattrape jamais la chaîne
déjà propagée.

**Décision : piste (b)** — le surveillant **rejoue les événements de transfert publics**, calcule
rétroactivement qui détient quoi dans le lot frauduleux (y compris les Ghost de paiement des
graines), et le **multisig 2/3** soumet la liste des destructions **et** des restitutions (§10bis
point 4) sous forme de **racine de Merkle**. Chaque porteur peut refaire le calcul et **contester**.

**Pourquoi (b) plutôt que (a), à couverture égale :**

1. **Coût on-chain nul par tranche.** (a) impose de stocker un identifiant d'origine sur **chaque**
   tranche d'échéance (§0bis-b) et de gérer la **fusion** de tranches d'origines différentes — du
   `SSTORE` et une sémantique de mélange à définir, à l'intérieur du contrat Ghost (#8) qui doit
   rester simple et auditable. (b) ne demande **aucun** stockage de lignage dans le contrat.
2. **Un seul mécanisme pour détruire ET restituer.** La §10bis (point 4) exige déjà que la liste
   de **restitutions** arrive sous forme de **racine de Merkle**. (b) fait transiter destructions
   et restitutions par **le même** chemin ; (a) aurait un lignage on-chain pour l'un et une racine
   de Merkle pour l'autre.
3. **Cohérent avec « l'IA ne décide jamais seule d'une destruction » (§3, §9).** Le calcul est
   hors chaîne et **public/reproductible** ; c'est le **multisig humain** qui engage la racine, et
   les porteurs peuvent la **contester** avant exécution. (a) déplacerait une partie de la décision
   dans l'automatisme on-chain du lignage.
4. **N'ajoute pas de dépendance de conception à #8.** Le contrat Ghost garde seulement un
   **point d'extension** (destruction acceptant une racine de Merkle) ; il n'a pas à porter le
   lignage. Cela **débloque #84** sans alourdir #8.

**Conséquence sur le comportement par défaut.** En l'absence de racine soumise, le contrat se
comporte comme la piste (c) : on n'atteint que ce que le voleur détient **encore** + ses Ghost de
paiement. (b) est le **sur-ensemble** activé par le multisig quand une chaîne a déjà propagé.

**Hypothèses explicites (à mesurer / documenter dans `docs/CLAIMS.md`, jamais garanties) :**

- Les événements de transfert sont **publics et complets** (le surveillant voit tout le lot).
- La **vitesse de détection** doit précéder l'échéance W du M' pour que la récupération soit totale ;
  au-delà de W, la part déjà convertie est **perdue** (c'est une friction, pas un échec du mécanisme).
- La racine de Merkle est **contestable** : le délai de contestation et le format de preuve
  (feuille = `(adresse, lot, montant_détruit, montant_restitué)`) sont à figer dans #84.

**Impact aval :**

- **#84 débloqué** : la destruction/restitution par racine de Merkle est la primitive attendue.
- **#8** : garde l'unique point d'extension « destruction par racine de Merkle » (déjà prévu sur
  `feat/8-ghost-token`), **sans** champ de lignage par tranche.
- **detection** : `python -m data.late_marking` fournit le calcul de référence ; un surveillant
  qui produit la liste rétroactive reste à brancher (hors périmètre #85, suivra avec #84).

### Reste ouvert

- Délai de **contestation** d'une racine soumise, et procédure de contestation (hors périmètre
  hackathon si le temps manque) — à décider avec #84.
- Format exact des **feuilles** de l'arbre de Merkle (destruction + restitution unifiées) — figé
  dans les tests d'invariants de #84.
- La récupération **au-delà de W** est hors de portée par construction : à **énoncer** comme limite
  dans `docs/CLAIMS.md`, pas à combler.

---

## §14. Lignage et conversions Ghost — plafonnement par `balanceOf` au semis (#104/#106)

### DÉCISION (2026-10-11, marceaupatu123) — option **(c)** : au moment du semis, plafonner le soupçon de chaque détenteur par `balanceOf(Ghost, addr)` lu on-chain

Le monitor émet les transferts Ghost ordinaires en `TransferEvent(is_ghost=True)` mais, comme
pour tous les tokens depuis #10, **n'émet pas les burns**, donc **pas les conversions**
(`Ghost → 0x0`). Or `detection.lineage.retroactive_seeds` reconstruit le solde Ghost non converti
en **rejouant** les transferts publics : sans la conversion dans le flux, un porteur qui a déjà
converti garde dans le rejeu un **solde fictif** et peut recevoir une graine pour du Ghost qu'il ne
détient plus. La destruction on-chain est plafonnée par le vrai solde (aucune perte de fonds), mais
la **restitution** et le **total « récupéré »** sont **surestimés**. C'est le trou décrit en §14 des
questions ouvertes.

**Option (c) retenue.** Au moment du semis, `retroactive_seeds` **plafonne le soupçon de chaque
détenteur par `balanceOf(Ghost, addr)` lu on-chain** : le solde servant à émettre chaque `AlertSeed`
(et donc le plafond et le ratio) devient `min(solde_reconstruit, balanceOf(addr))`. C'est **la vérité
de la chaîne** — le solde réel au moment du semis — et c'est **le plus simple** : aucun nouveau flux,
aucune reconstruction supplémentaire des conversions, un seul point de branchement.

**Pourquoi pas (a) ni (b) maintenant :**

- **(a)** — émettre aussi les burns/conversions comme `TransferEvent(recipient=0x0, is_ghost=True)` —
  est **écartée** : elle oblige à **filtrer de faux transferts** dans les règles de détection de
  transfert (volume, HHI), qui compteraient alors des conversions comme du trafic. Coût de conception
  et risque de faux positifs non voulus hors du périmètre de ce correctif.
- **(b)** — un flux dédié aux conversions (`GhostConverted` est déjà décodé par le monitor), passé à
  `retroactive_seeds` comme soldes initiaux ou comme sorties — **reste l'évolution propre** si le coût
  RPC d'une lecture par graine devient gênant. On ne l'implémente pas tant que la mesure ne le justifie
  pas.

**Mise en œuvre (option c).** `retroactive_seeds` reçoit un paramètre **optionnel**
`ghost_balance_of: Callable[[str], int] | None = None` — une fonction injectable `addr -> solde`,
pour rester **testable et déterministe hors ligne** (pas d'appel RPC en dur dans le module). Quand il
est fourni, le solde final de chaque détenteur est plafonné par `ghost_balance_of(addr)` ; quand il
est `None`, le comportement actuel est **inchangé** (rétrocompatibilité). L'appelant branche
`ghost_balance_of` sur un vrai `balanceOf` du contrat Ghost (**une lecture RPC par graine**).

**Limite mesurée — à documenter dans `docs/CLAIMS.md`, jamais estimée.** Le coût est **une lecture
RPC par graine** au semis. Le rejeu seul (`ghost_balance_of=None`) **peut surestimer** si une
conversion n'a pas été vue : c'est exactement le trou §14, et (c) le ferme en lisant la vérité
on-chain au moment du semis. Si ce coût RPC gêne à l'échelle, basculer vers (b).

### Reste ouvert

- Branchement de `ghost_balance_of` sur une vraie lecture `balanceOf` côté appelant (hors
  périmètre de ce correctif, qui garde le module déterministe et hors ligne).
- Mesure du coût RPC réel (une lecture par graine) à **chiffrer** dans `docs/CLAIMS.md` avant toute
  affirmation ; bascule vers (b) si la mesure le justifie.


