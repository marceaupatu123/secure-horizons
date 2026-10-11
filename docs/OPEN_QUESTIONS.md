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
> assumées et option intermédiaire écartée). Les questions existentielles ci-dessus restent
> ouvertes.
>
> **#35 (transfert d'un Ghost)** → Tranché, voir `docs/OPEN_ANSWERS.md` §0bis-b : un seul Ghost
> par token, la fenêtre est portée par la valeur et ne redémarre pas en circulant ; tranches
> d'échéance bornées par adresse.
>
> **#36 (collatéral orphelin)** → Tranché, voir `docs/OPEN_ANSWERS.md` §0bis-c : invariant `≤`,
> l'excédent forme une réserve de restitution cantonnée, restitution par multisig 2/3 plafonnée
> par la réserve.
>
> **#37 (solvabilité vs récupération dans `CLAIMS.md`)** → Tranché, voir `docs/OPEN_ANSWERS.md`
> §0bis (deux affirmations distinctes, solvabilité en tête).

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

### Propositions (2026-10-10, Yannis) — _proposé, à valider en équipe, **non acté**_

> Ce sont des **propositions** pour répondre aux points ci-dessus, pas des décisions. Rien n'ira
> dans `docs/OPEN_ANSWERS.md` tant que l'équipe ne les a pas actées.

1. **⚠️ PRIORITÉ HAUTE — délai de détection.** La détection doit être **plus rapide que la fenêtre
   Ghost normale** (10 min, §0bis), sinon les fonds de l'attaquant sont déjà convertis quand
   l'alerte arrive. Des agrégats journaliers/horaires (ligne « volume agrégé » ci-dessus) arrivent
   donc trop tard. Proposition : mesurer par **tranches de 5 min**, comparées à la baseline
   médiane + MAD **du même créneau** (§9).
2. **« Adresse neuve »** : pour la démo, **aucune transaction avant T dans notre jeu de données**
   (le plus simple sur des données synthétiques). Amélioration future : **moins de K transactions
   au total**, qui résiste à un attaquant qui « chauffe » ses adresses à l'avance.
3. **« Point de sortie »** : une **liste fixe d'adresses étiquetées** « exchange » ou « bridge »,
   produite par le générateur de données. → **À signaler au propriétaire de `data/`
   (@EnzoFB06, #24).**
4. **Mesure de la dispersion** (le discriminant de la §9) :
   - mesure de référence : **indice de Herfindahl** (somme des parts au carré des destinataires ;
     proche de 1 quand tout part au même endroit) ;
   - exposée en plus : le **nombre de destinataires distincts**, plus facile à montrer au jury
     sur le dashboard ;
     ⚠️ **limite repérée (exemple chiffré, 2026-10-10)** : dans l'exemple du mint de 50M vers
     3 adresses puis 4 bridges, ce nombre passe de ~150 à ~157 et ne **montre presque pas**
     l'attaque, alors que le Herfindahl est multiplié par ~20. Il ne doit pas être présenté seul
     comme indicateur d'attaque ;
   - les signaux par transfert (gros montant vers adresse neuve, découpage, sortie rapide,
     concentration vers les sorties, éventail/*fan-out*) **alimentent uniquement** la mesure de
     dispersion ; ce ne sont **pas** des surveillants séparés, pour rester simple.
5. **Rebonds comptés une fois (#87) — _choix provisoire de l'assistant (2026-10-11, pour Yannis),
   à valider en équipe_.** Avant, chaque rebond ajoutait son montant : l'exemple de référence
   (50M → 3 adresses neuves → 4 bridges) comptait **100M**. Règle retenue : volume d'une tranche =
   **somme des soldes entrants nets positifs** (reçu − envoyé par adresse, dans la tranche). Le
   Herfindahl est calculé sur les mêmes soldes nets (les relais ne sont plus des destinataires).
   Le volume brut reste exposé (`gross_volume`).
   - **Limites** : indifférent à l'ordre dans la tranche ; un aller-retour A → B → A compte 0
     (le *wash trading* devient invisible au volume) ; deux flux indépendants qui se croisent
     sur une adresse se compensent.
   - **Alternative écartée** : suivre chaque montant par lignage (FIFO) — plus juste, mais coûteux
     et redondant avec le lignage de §10/§11.
   - **Effet mesuré** (`python -m data.calibrate`, simulation, seed par défaut, profil
     `gros_transferts`) : l'attaque B à 0,5 % de l'offre est désormais détectée avant conversion
     pour z HHI ∈ {2, 3}, au prix de 0 à 2 faux positifs de plus sur 864 tranches selon le couple
     de seuils. Les autres profils et tables ne bougent pas. Mesure sur données fictives
     (`docs/CLAIMS.md`), pas une garantie.

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
- Alignement de `response/orchestrator.py` (fait, PR #56), `CLAUDE.md` (fait) et des champs `ResponseAction`
  (`docs/CONTRACTS.md`) sur le vocabulaire et la machine à états actés.

#### Points faibles repérés (2026-10-10, Yannis) — _sur un exemple chiffré fictif, à traiter en équipe_

Exemple : mint frauduleux de 50M, réparti sur 3 adresses neuves puis envoyé vers 4 bridges en
2 min. Les chiffres de l'exemple sont inventés ; seuls les mécanismes comptent.

- **Le silence des humains profite à l'attaquant.** « Silence = retour auto à la normale » : si
  le multisig ne signe pas avant la fin du retard, la fenêtre revient à la normale et les Ghost
  suspects se **convertissent**. La durée du retard doit donc être **plus longue que le temps de
  réaction réel du multisig**. Ce temps n'est pas mesuré. À décider : durée minimale du retard, et
  faut-il une escalade (notification répétée, retard prolongé une fois) avant l'expiration ?
- **Le budget de quarantaine (§9) peut empêcher l'IA de retarder.** Dans l'exemple, ~33 % de
  l'offre passe en fenêtre allongée d'un coup. Si le budget est plus bas, l'IA ne peut **pas**
  retarder seule et il faut un humain **immédiatement**, au pire moment. À décider : valeur du
  budget, et ce qui se passe quand une seule alerte le dépasse (retard partiel sur les graines ?
  appel humain bloquant ?).

## 4. Angle différenciant (à choisir)

> **TRANCHÉ par la décision §4 (2026-10-10, Équipe 20)** — texte complet dans
> `docs/OPEN_ANSWERS.md`. Résumé : pas un angle isolé mais **un principal + deux renforts**,
> unifiés par la thèse « **pricer le risque** » (le risque comme signal continu). Principal =
> **protection des protocoles en aval / anti-contagion** (seul angle démontrable, scénario C) ;
> renfort A = **supervision de l'agent de réponse** (§3/§9) ; renfort B = **cadre DORA**
> (journal d'audit + rapport d'incident, narratif, pas angle technique isolé).

### Reste ouvert (voir §4 d'`OPEN_ANSWERS.md`)

- Angle DORA « prestataire tiers critique » gardé comme narratif seulement.
- Chiffres du scénario C (mauvaises créances avec vs sans balise), **à mesurer**.

## 5. Mesure de performance

> → **Tranché**, voir `docs/OPEN_ANSWERS.md` §5 (validée en session, à relire par l'équipe).
> Résumé : tout se mesure par rapport à la fenêtre Ghost (détecter **avant conversion**) ; délai =
> `t2 − t0` + **marge avant conversion** ; FP mesurés sur un **jeu de trafic normal sans attaque**
> (#24), par fenêtre d'agrégation (plus courte que la fenêtre Ghost) ET en part d'offre retardée ;
> baseline = Resolv tel quel ; critères de succès par scénario (A/B/C/D) ; chaque claim de
> `CLAIMS.md` doit avoir sa mesure.

- Comment mesurer le **délai de détection** (de l'événement on-chain à l'alerte) ?
- Comment mesurer le **taux de faux positifs** (et sur quel jeu de données) ?
- Quelle **baseline** et quels critères de succès pour la démo ?

### Reste ouvert (voir §5 d'`OPEN_ANSWERS.md`)

- Valeur de la fenêtre d'agrégation (candidate : 5 min, §2) et du seuil de déclenchement, **à
  mesurer**.
- Nombre de rejeux N, choix médiane / p95.
- Dépend du générateur de données (#24) : trafic normal horodaté sans attaque.

## 6. Données synthétiques (voir `data/README.md`)

> **TRANCHÉ par la décision §6 (2026-10-10, EnzoFB06, propriétaire `data/`)** — texte complet dans
> `docs/OPEN_ANSWERS.md`. Résumé : format **JSONL** (une ligne = un événement) ; **schéma = les
> modèles figés de `docs/CONTRACTS.md`** (pas de schéma dupliqué) ; scénarios recadrés — **A** mint
> gonflé (Resolv), **B** reformulé en détournement 1:1 / hypothèse du volet 1 qui tombe (ferme
> #49), **C** contagion et **D** marché Ghost inchangés ; **flux de trafic normal** par créneaux de
> 5 min comme base de calibration ; générateur `data/generate.py` (`make data`) à graine fixe,
> important les modèles de `shared/`.

### Reste ouvert (voir §6 d'`OPEN_ANSWERS.md`)

- Valeurs exactes (volumes, saisonnalité, N adresses, ratios), **à mesurer**.
- Liste des adresses « point de sortie » (coord. §2).
- Committer les JSONL ou seulement le générateur + la graine ? (taille vs reproductibilité).
- Variante retenue pour B (détournement 1:1 vs événement admin). Seul le détournement 1:1 est
  généré : l'événement admin n'a pas de modèle partagé.
- `.gitignore` pour `data/generated/` (sorties de `make data`).

## 7. Interfaces entre modules (voir `docs/CONTRACTS.md`)

> → **Spécifié et mergé (PR #53, issue #2 fermée).** Les 13 modèles sont figés en Pydantic strict (`extra="forbid"`),
> identités EVM (adresses/hash validés), montants en entiers base units, timestamps UTC. Le soupçon
> est porté par `contamination_ratio` (0–1) + `suspect_amount` (int). Détail complet et exemples
> JSON dans `docs/CONTRACTS.md`. Reste à acter : relecture et merge de la PR.

- Champs de `MintEvent`, `TransferEvent`, `Alert`, `ResponseAction`, `AuditLogEntry`.
- Où vivent les modèles (`shared/`), format d'échange (JSON ?), versionnage éventuel.

### Proposition (2026-10-10, Yannis) — _intégrée dans la PR #53_

- **`Alert` doit désigner un périmètre, pas seulement « anomalie ».** Le modèle de contamination
  par ratio (§9) a besoin de savoir **quelles adresses marquer suspectes au départ** (les
  « graines ») et pour **quels montants**.
  → **Pris en compte** : la PR #53 ajoute le modèle `AlertSeed` (adresse + `suspect_amount` +
  `contamination_ratio`) et le champ `Alert.seeds: list[AlertSeed]`. À valider à la relecture.

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
> ouvert : valeur de tous les seuils (à mesurer) et relecture d'équipe. #35/#36 tranchés en
> §0bis-b/§0bis-c d'`OPEN_ANSWERS.md`.

#### Point faible repéré (2026-10-10, Yannis) — _sur un exemple chiffré fictif, à traiter en équipe_

- **Un utilisateur légitime peut être retardé par ricochet.** Un bridge qui reçoit des Ghost
  suspects voit son ratio monter (ex. ~0,93). Un utilisateur normal qui envoie 5 000 M vers ce
  bridge dans le même créneau n'est **pas détruit** (la destruction ne prend que ratio × solde,
  donc la part suspecte), mais la conversion du bridge **attend la fin de l'audit** : l'argent
  légitime est bloqué avec le reste. À décider : ce retard collatéral est-il acceptable, et faut-il
  le mesurer (part du volume légitime retardée par alerte) en plus de la friction max bornée ?
  Les autres points faibles du même exemple sont en §3.

## 10. Lignage transactionnel — reverter les deux jambes d'un échange — _proposé, à valider en équipe_

> → **Tranché (#43)**, voir `docs/OPEN_ANSWERS.md` §10 : `swap-id` sur **notre** pool seulement ;
> la jambe sortante (USDC) est payée en **règlement différé** à l'échéance du Ghost vendu, et
> annulée à hauteur du ratio du vendeur si une destruction est confirmée. DEX tiers : limite
> assumée (ratio + balise de risque seulement). Le texte ci-dessous est conservé pour l'historique.

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

> → **Étendu, voir `docs/OPEN_ANSWERS.md` §10bis (#84)** : le voleur ne reçoit jamais que du Ghost
> (paiement bloqué dans le coffre de l'actif, vendeur payé en Ghost de cet actif via un routeur) ;
> M' **protégé** (acheté contre du vrai M), **pur** (acheté avant échéance, à risque) ou **chèque**
> (reçu sans paiement) ; l'argent bloqué du voleur est **restitué aux victimes**, le protocole ne
> garde rien (ni fonds, ni frais). Le stablecoin pivot Z permanent reste écarté.

## 11. Contamination posée après coup (#85) — _→ Tranché, voir `docs/OPEN_ANSWERS.md` §11_

> **TRANCHÉ par la décision §11 (2026-10-11, denybs)** — texte complet et mesure (`python -m
> data.late_marking`, PR #95) dans `docs/OPEN_ANSWERS.md` §11. Résumé : **piste (b)** — recalcul
> hors chaîne des ratios rétroactifs, destructions **et** restitutions soumises par le **multisig
> 2/3** sous forme de **racine de Merkle contestable**. (a) et (b) récupèrent 100 % à couverture
> égale (mesuré) ; (b) retenue car **coût on-chain nul par tranche**, **un seul mécanisme**
> destruction+restitution, et cohérence avec « l'IA ne décide jamais seule ». Débloque #84 ;
> #8 garde seulement le point d'extension « destruction par racine de Merkle ».

Contexte conservé (pistes évaluées) :

- **(a) Lignage d'origine sur la tranche** : chaque tranche (§0bis-b) garde l'identifiant de son
  entrée dans le Ghost (mint, transfert de vrai M). L'alerte vise une **origine**, pas une adresse.
  Coût : stockage par tranche ; que faire quand deux origines se mélangent dans une même tranche ?
- **(b) Recalcul hors chaîne + preuve** : le surveillant rejoue les événements, calcule les ratios
  rétroactifs, et le multisig soumet la liste des destructions (racine de Merkle). Coût : confiance
  dans le calcul, contestabilité par les porteurs.
- **(c) Contamination prospective seulement** : on n'atteint que ce que le voleur détient encore et
  ses Ghost de paiement. Simple, mais le M' déjà propagé n'est pas rattrapé (le dernier acheteur de
  M' pur garde alors un M' frauduleux qui se convertit).

Tests d'invariants associés dans #8 / #84 (voir la décision §11 d'`OPEN_ANSWERS.md`). Aucun chiffre inventé.

## 12. Monitor — reprise sur erreur RPC et checkpoint (#74) — _choix provisoires, à valider en équipe_

Choix faits par l'assistant (2026-10-11, pour Yannis) pour que la surveillance ne se coupe plus en
silence (fail-open). Tous configurables dans `monitor/config.py`, aucun chiffre mesuré :

- **Retry sans limite** des appels RPC (attente exponentielle 1 s → plafond 30 s). Alternative
  écartée : s'arrêter après N échecs — un monitor arrêté est pire qu'un monitor qui réessaie.
- **Escalade** : après 5 échecs consécutifs, log ERROR « SURVEILLANCE AVEUGLE ». À brancher plus
  tard sur `response`/dashboard (aujourd'hui : log seulement). Faut-il geler par précaution quand
  le monitor est aveugle plus d'une fenêtre Ghost ? **Ouvert.**
- **Log mal formé** : ignoré + log ERROR (au lieu de couper tout le flux).
- **Checkpoint fichier local**, sémantique « au moins une fois », **désactivé par défaut** (un
  fichier par process). À revoir si le monitor tourne en plusieurs instances.

## 13. Surveillant ML / prédiction conforme (#13) — _mesuré, proposition à valider en équipe_

Implémenté en piste de recherche, **non branché** (`detection/conformal.py`,
`python -m detection.conformal_eval`). Choix de l'assistant (2026-10-11, pour Yannis) :
`IsolationForest` sur les ratios de tranche, partage 50/50 entraînement/calibration aléatoire
(graine fixe), 7 jours d'apprentissage, test sur le 8e jour (jamais vu), W = 10 min.

Mesure (seed 42, données fictives, après #87) :

| profil | α | FP mesuré (288 tranches) | B 0,5 % | B 2 % | B 5 % | B 10 % |
|---|---|---|---|---|---|---|
| gros_transferts | 1 % | 1,0 % | non | oui | oui | oui |
| gros_transferts | 5 % | 4,5 % | non | oui | oui | oui |
| petits_transferts | 1 % | 0,7 % | oui | oui | oui | oui |
| petits_transferts | 5 % | 3,8 % | oui | oui | oui | oui |

Lecture : la borne de faux positifs **tient** sur ce trafic (FP ≈ α), mais les règles actuelles
font mieux (z volume = z HHI = 3 : 2/864 tranches en FP, B 0,5 % détecté avant conversion). La
garantie suppose que le trafic testé ressemble au trafic de calibration (pas de croissance, pas
d'usage nouveau) — hypothèse qu'un vrai protocole ne vérifie pas.

**Proposition** : garder les seuils simples pour la démo (confirme OPEN_ANSWERS §1) ; citer la
prédiction conforme au jury comme piste mesurée, avec sa limite. Une seule graine mesurée : à
répéter avant toute affirmation chiffrée (`docs/CLAIMS.md`).
