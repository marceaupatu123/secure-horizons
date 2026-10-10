# OPEN_QUESTIONS.md — décisions à prendre en équipe

Ce fichier liste les décisions de conception **non tranchées**. Aucune n'est décidée par un
assistant IA : on les discute et on les acte ici (ajouter la décision + la date sous chaque point).
Dès qu'une décision est actée, son **texte complet est déplacé** dans `docs/OPEN_ANSWERS.md` ;
ici il ne reste qu'un **renvoi** « → Tranché, voir `docs/OPEN_ANSWERS.md` §… », avec les questions
et conséquences qui, elles, restent ouvertes.

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

> → **Tranché**, voir `docs/OPEN_ANSWERS.md` §0bis (texte complet de la décision, conséquences
> assumées et option intermédiaire écartée). Les questions existentielles ci-dessus et les
> questions dérivées #35, #36, #37 restent ouvertes.

## 1. Détection du mint anormal

> → **Tranché**, voir `docs/OPEN_ANSWERS.md` §1 (validée en session, à relire par l'équipe).
> Résumé : pas de seuil sur la taille d'un mint (redondant avec le volet 1) ; le surveillant
> vérifie hors chaîne que les hypothèses du volet 1 tiennent (invariants, événements admin,
> oracle) ; nouvel invariant I3 « destinataire = déposant » à appliquer dans le contrat.

- Quels **invariants** doit respecter le système de mint (ex : tokens émis ≤ f(collatéral)) ?
- Quels **seuils** déclenchent une anomalie de mint (absolus, relatifs, fenêtre temporelle) ?
- Comment distinguer un mint légitime important d'un mint malveillant ?

### Reste ouvert (voir §1 d'`OPEN_ANSWERS.md`)

- Valeurs de ε (frais) et δ (écart d'oracle), source de référence du taux, **à mesurer**.
- Contrat upgradable ou non.
- Liste exacte des événements d'administration à surveiller.
- Reformulation du scénario B (#49).

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

> **TRANCHÉ par la décision §3 (2026-10-10, Équipe 20)** — texte complet dans
> `docs/OPEN_ANSWERS.md`. Résumé : « retarder » n'est pas « bloquer » ; pendant un retard les
> Ghost **circulent** mais ne se **convertissent** pas ; silence = retour auto à la normale ;
> quorums multisig **2/3 pour détruire**, **3/3 pour la pause globale** (levée par le même
> multisig) ; machine à états `NORMAL → RETARDÉ → {NORMAL | DÉTRUIT | PAUSE_GLOBALE}`. S'appuie
> sur les trois verbes de la §9.

### Reste ouvert (voir §3 d'`OPEN_ANSWERS.md`)

- Valeurs exactes (facteur d'allongement, durées, seuils d'escalade), **à mesurer**.
- Canal et destinataires de la notification d'audit humain.
- Alignement de `response/orchestrator.py`, `CLAUDE.md` et des champs `ResponseAction`
  (`docs/CONTRACTS.md`) sur le vocabulaire et la machine à états actés.

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

> → **Tranché**, voir `docs/OPEN_ANSWERS.md` §9 (texte complet : principe, trois verbes,
> distinction attaque/croissance, contamination par ratio, garde-fous et limites assumées). Reste
> ouvert : valeur de tous les seuils (à mesurer), relecture d'équipe, et #35/#36.

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
