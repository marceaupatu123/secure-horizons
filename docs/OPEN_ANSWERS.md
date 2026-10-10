# OPEN_ANSWERS.md — décisions tranchées en équipe

Ce fichier regroupe les questions de `docs/OPEN_QUESTIONS.md` qui ont reçu une **décision
actée** (marquée « DÉCISION », avec une date et un auteur). Les textes ci-dessous sont des
**copies** : chaque décision reste aussi dans `OPEN_QUESTIONS.md`, avec un renvoi ici, parce que
ses conséquences et ses questions dérivées sont encore ouvertes.

Règles :

- On n'ajoute ici que ce qui est marqué **DÉCISION** dans `OPEN_QUESTIONS.md`. Une proposition
  « par défaut, à confirmer » (ex. §8 `BEDROCK_MODEL_ID`) reste dans les questions.
- Le statut est recopié tel quel (ex. « à relire par l'équipe ») : on ne le renforce pas.
- Toute modification d'une décision se fait **dans les deux fichiers**.

## Index

| § | Question tranchée | Date | Par | Statut | Source |
|---|-------------------|------|-----|--------|--------|
| 0bis | Le Token Ghost s'applique-t-il au seul mint ou à tous les transferts ? | 2026-10-10 | Marceau | Tranché | PR #34 |
| 9 | Volet 2 : surveillance adaptative, allongement de fenêtre ciblé, contamination par ratio | 2026-10-10 | Marceau | Validée en session, à relire par l'équipe | PR #38 |

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
- #35 : que produit le transfert d'un Token Ghost (Ghost d'un Ghost) ?
- #36 : que devient le collatéral quand on brûle un Ghost adossé (collatéral orphelin) ?
- #37 : aligner `CLAIMS.md` sur l'objectif de la décision (solvabilité ou récupération).

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
- #35 et #36 ne sont pas abordés par cette décision.
