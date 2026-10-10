# OPEN_QUESTIONS.md — décisions à prendre en équipe

Ce fichier liste les décisions de conception **non tranchées**. Aucune n'est décidée par un
assistant IA : on les discute et on les acte ici (ajouter la décision + la date sous chaque point).
Chaque décision actée est aussi **copiée** dans `docs/OPEN_ANSWERS.md` (elle reste ici, avec un
renvoi, tant que ses conséquences sont ouvertes).

## 0. Décision structurante — _proposé, à valider en équipe_

> **TRANCHÉ par la décision §0 (2026-10-10, Équipe 20)** : sécurité **dans le contrat** ; cœur du
> projet = **pricer le risque** via le Token Ghost à contamination par ratio ; pas de plafond fixe
> mais une **baseline adaptative** ; volet 3 retenu comme cœur ; priorité volet 1 → 2 → 3 ; marge
> à la conversion token ⇄ Ghost. Copie et détails dans `docs/OPEN_ANSWERS.md`.

**La sécurité vit-elle dans le contrat (montant dérivé on-chain, plafonds, quarantaine, multisig)
ou seulement autour (surveillance + pause) ?**

Sous-questions liées (à ne pas trancher ici) :

- Le **montant dérivé on-chain** est-il compatible avec notre faux protocole, et que devient la
  **signature** (autorise « traiter la demande n°X » plutôt qu'un montant) ?
- Quels **plafonds** (par opération, par heure, éventuellement adaptatifs) et quelle **fenêtre de
  quarantaine**, et quel impact sur les utilisateurs légitimes ?
- Comment **calculer et présenter la perte maximale bornée**, et sous quelles **hypothèses**
  (plafonds appliqués on-chain, clés d'administration non compromises) ?
- **Qui peut geler, qui peut lever un gel**, et comment (multisig, rôles, veto asymétrique) ?
- Faut-il construire la **balise de risque** et le **faux marché de prêt** (volet 3), ou rester
  sur le **contrat seul** si le temps manque ?
- **Combien de surveillants** et de quels types (règles, ML, signaux de transferts) ?
- Faut-il tenter la **prédiction conforme** pour borner les faux positifs, ou rester sur des
  **seuils simples** ?
- **Ordre de priorité si le temps manque** (proposition : volet 1, puis volet 2, puis volet 3).

## 0bis. Pivot « quarantaine liquide / Token Ghost » — _proposé, à valider en équipe_

Questions existentielles ouvertes par ce pivot (**tout transfert** émet un **Token Ghost** librement
échangeable, converti 1:1 après délai sans anomalie, **détruit** si un gel est confirmé ; le
risque est transféré vers un marché secondaire spéculatif) :

- Le **transfert de la perte financière** vers des acteurs du marché secondaire est-il conforme à
  l'**esprit du règlement DORA**, qui vise à protéger l'écosystème global (et pas seulement le
  protocole émetteur) ?
- Comment gérer **techniquement la destruction** d'un Token Ghost qui a été **fragmenté et envoyé
  à 50 adresses différentes** (ou plus) ?
- Quel est l'**impact sur la liquidité** (pools DeFi) si un jeton échangeable **disparaît
  soudainement** de leurs réserves ?

### DÉCISION (2026-10-10, Marceau) — le Ghost s'applique à **tous les transferts**

> → **Tranché**, voir `docs/OPEN_ANSWERS.md` §0bis. Conséquences et questions dérivées (#35, #36,
> #37) encore ouvertes.

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

## 1. Détection du mint anormal

- Quels **invariants** doit respecter le système de mint (ex : tokens émis ≤ f(collatéral)) ?
- Quels **seuils** déclenchent une anomalie de mint (absolus, relatifs, fenêtre temporelle) ?
- Comment distinguer un mint légitime important d'un mint malveillant ?

## 2. Signaux de transferts anormaux

> **Complété par la décision §9 (2026-10-10)** : le discriminant retenu contre les faux positifs
> de croissance est **volume élevé ET dispersion effondrée** sur des **ratios normalisés** (pas de
> volumes absolus), baseline **médiane + MAD**. Voir §9.

- Quels **signaux** retenir : gros montant vers adresse neuve, découpage (structuring), vitesse de
  sortie, concentration vers des points de sortie (échanges) ?
- **Volume agrégé anormal** (journalier/horaire) normalisé par le collatéral ou l'offre en
  circulation — signal ajouté par §9.
- Comment pondérer/combiner ces signaux (règles, score, modèle `scikit-learn`) ?
- Qu'est-ce qu'une « adresse neuve » et un « point de sortie » dans notre modèle ?

## 3. Réponse graduée — automatique vs validation humaine

> **En grande partie répondu par la décision §9 (2026-10-10)** : trois verbes distincts
> (retarder / détruire / pause globale), l'IA ne fait que **retarder** (auto-expirant), humains
> multisig pour détruire et pour la pause globale. Voir §9.

- Quels cas déclenchent un **blocage automatique** (pause réversible) ? → §9 : allongement de
  fenêtre Ghost, auto-expirant, décidable par un surveillant/IA.
- Quels cas exigent une **validation humaine** avant action ? → §9 : destruction et pause globale.
- Comment garantir la **réversibilité** de la pause ? Qui a le droit de valider/relâcher ? → §9 :
  l'allongement expire seul ; la levée d'une destruction/pause passe par multisig.

## 4. Angle différenciant (à choisir)

- Lien **incident / prestataire tiers critique** au sens **DORA** ?
- **Protection des protocoles en aval** (effet de contagion) ?
- **Supervision de l'agent de réponse** (garde-fou sur l'IA qui décide) ?
- Autre angle proposé par l'équipe ?

## 5. Mesure de performance

- Comment mesurer le **délai de détection** (de l'événement on-chain à l'alerte) ?
- Comment mesurer le **taux de faux positifs** (et sur quel jeu de données) ?
- Quelle **baseline** et quels critères de succès pour la démo ?

## 6. Données synthétiques (voir `data/README.md`)

- Format des fichiers (CSV / JSON / JSONL ?) et schéma des lignes.
- Paramètres précis des scénarios **A** (mint détecté) et **B** (transferts détectés).
- Outil de génération et commande de lancement.

## 7. Interfaces entre modules (voir `docs/CONTRACTS.md`)

- Champs de `MintEvent`, `TransferEvent`, `Alert`, `ResponseAction`, `AuditLogEntry`.
- Où vivent les modèles (`shared/`), format d'échange (JSON ?), versionnage éventuel.

## 8. `BEDROCK_MODEL_ID` — choix du modèle LLM (#28) — _proposé par défaut, à confirmer_

Setup #28 : accès Bedrock vérifié sur le compte atelier (`us-east-1`). Les modèles accessibles
sont des **inference profiles** (ids préfixés `us.` / `global.`), à passer tels quels à l'API
Converse.

**Proposition par défaut retenue dans `.env.example` :**

```
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Raisons : inference profile (attendu par Converse en `us-east-1`), id **daté/versionné** donc
stable et reproductible pour la démo, bonne qualité rédactionnelle pour le rapport d'incident DORA,
coût négligeable vu que le LLM est appelé **uniquement sur alerte**.

Alternatives valables si l'équipe préfère plus léger/rapide :

- `us.anthropic.claude-haiku-4-5-20251001-v1:0` (Haiku 4.5 — plus rapide, moins cher).

À **éviter** : les alias courts non datés (ex. `...claude-sonnet-5`) — plus volatils, mauvais pour
la reproductibilité.

> Rappel : le compte atelier est **temporaire** (credentials de session STS qui expirent). Le
> `BEDROCK_MODEL_ID` ne dépend pas du compte et reste valable ; seuls les credentials sont à
> renouveler à chaque session.

## 9. Volet 2 — surveillance adaptative, allongement de fenêtre ciblé et modèle de contamination par ratio

### DÉCISION (2026-10-10, Marceau) — _validée en session, à relire par l'équipe_

> → **Tranché**, voir `docs/OPEN_ANSWERS.md` §9. Seuils à mesurer, relecture d'équipe et #35/#36
> encore ouverts.

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

## 10. Lignage transactionnel — reverter les deux jambes d'un échange — _proposé, à valider en équipe_

### Besoin

Un échange est **atomique** : USDC ↔ Crypto-M, c'est deux jambes d'une même opération. Si une
fraude est confirmée et qu'on revert la jambe M, il faut pouvoir revert **l'autre jambe** aussi —
sinon l'attaquant qui a troqué son M suspect contre de l'USDC et s'est enfui avec l'USDC n'est pas
rattrapé.

### Idée initiale (évaluée) : un stablecoin pivot « Z »

Faire transiter **tous** les échanges par un token maison **Z** (pool `Z / Z-Ghost`) : vendre M
donnerait du M-Ghost à l'acheteur et du Z-Ghost au vendeur, les deux liés et traçables.

**Écartée sous cette forme.** Raison : *où est le vrai USDC pendant que le Z-Ghost circule ?*

- Si le contrat détient l'USDC et émet du Z adossé → on **reconstruit un stablecoin
  collatéralisé** et on redevient **dépositaire de fonds réels** : cible n°1, risque recentralisé.
  C'est précisément le type de brique que le projet combat (scénario Resolv).
- Si Z n'est pas adossé → au premier doute, personne n'accepte Z, le pool est mort-né.
- En plus : forcer 100 % des échanges par un token maison crée un **point de passage obligé
  centralisé** — contraire à l'esprit **DORA** (réduire la dépendance à un prestataire critique
  unique, pas en créer un).

### Variante retenue à discuter : lignage transactionnel (sans token Z)

Garder le bénéfice (reverter les deux jambes) **sans** émettre ni custodier de stablecoin :

> Les deux jambes d'un même swap reçoivent un **identifiant de lignage commun** (`swap-id`).
> L'échange produit du M-Ghost côté acheteur et un **Ghost sur l'actif sortant** côté vendeur, tous
> deux marqués du même `swap-id`. En cas de gel, on revert les deux via ce lien.

- Réutilise **exactement** le mécanisme de lignage par ratio déjà décidé (§9, #33) : le `swap-id`
  est une **relation** « ces deux Ghost appartiennent au même swap », pas un nouveau token.
- Pas de nouveau risque de garde, pas de stablecoin, pas de point central.

### Questions ouvertes pour cette variante

- Comment un **DEX/AMM tiers** (qu'on ne contrôle pas) marquerait-il les deux jambes d'un même
  `swap-id` ? Faisable seulement sur **notre** pool, ou aussi en lecture d'événements externes ?
- Que signifie « reverter la jambe sortante » si l'actif sortant est un **actif externe** (USDC)
  qu'on ne peut pas détruire comme un Ghost maison ? (Probablement : on ne peut reverter que les
  jambes **en Ghost sous notre contrôle** — à cadrer honnêtement.)
- Interaction avec le ratio de contamination : le `swap-id` propage-t-il aussi le soupçon entre
  jambes, ou seulement le lien de revert ?

> **Statut** : l'option « token Z » est écartée ; la variante « lignage transactionnel » est
> **proposée, non actée**. À trancher en équipe. Aucun chiffre, aucune promesse non mesurée.
