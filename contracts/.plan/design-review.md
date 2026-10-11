# Revue de design — Token Ghost (#8), RiskBeacon + MockLendingMarket (#7), pool (#65)

Itération 2. Revue à froid de `contracts/.plan/design.md` (révision après l'itération 1),
recoupée avec `docs/OPEN_ANSWERS.md` (§0, §0bis dont la décision #37 « deux affirmations »,
§0bis-b, §0bis-c, §3, §4, §9, §10), `docs/CONTRACTS.md` (`RiskBeaconUpdate`,
`GhostTokenMintEvent`), `src/ProtectedMinter.sol`, `src/GuardianPausable.sol`,
`src/StableToken.sol`, `test/utils/BaseTest.sol`, les suites `test/**` citées en §8.1,
`foundry.toml`, `lib/openzeppelin-contracts/package.json`, et sur `origin/main` (contexte transmis
par l'orchestrateur) `data/ghost_ledger.py`, `data/scenarios_cd.py` (#25, PR #82) et
`monitor/listener.py` (#9 / #10). Les décisions ne sont pas rediscutées ; seule leur projection
sur le contrat et les tests est jugée.

**Verdict : CHANGES_REQUESTED** — 1 HIGH (n° 1), 4 MEDIUM (n° 2, 3, 3bis, 3ter), 12 NIT (n° 4–15).

Les 4 HIGH et 6 MEDIUM de l'itération 1 sont traités correctement (vérifié point par point, voir
« Hypothèses vérifiées »). Les constats restants sont nouveaux ou viennent des ajouts de
l'itération 2.

## Constats

### 1. HIGH — Scénario C : la mauvaise créance « sans balise » vaut 0 par construction

Où : §8.3 `ScenarioC.t.sol` (« Mauvaise créance par marché = `dette − valeur(ghost + m −
suspect)` de la position attaquante » ; « assertion … `ghost brûlé chez le marché == Σ suspect` »),
§5 (`useBeacon == false` ⇒ `p.suspect` reste 0, testé par `vm.expectCall(…, 0)`).

Problème : `suspect` désigne le champ `Position.suspect`. Dans le marché `useBeacon = false`,
il vaut 0 par construction. La formule donne alors `max(0, dette − valeur(ghost + m))`, et
comme `dette ≤ valeur × ltv / 10_000 ≤ valeur`, le résultat est **toujours 0**. Dans le marché
avec balise (variante 1), l'emprunt est refusé (`RETARDE`), donc dette = 0 et créance = 0. Le
chiffre phare de la démo (§4, « angle principal, seul angle démontrable ») sort donc à
`0 vs 0`. L'assertion `avec ≤ sans` passe sans rien prouver. L'assertion
`ghost brûlé chez le marché == Σ suspect` échoue pour le marché sans balise (brûlé > 0,
`Σ p.suspect = 0`). La mesure doit venir de la vérité côté Ghost, pas du livre de risque propre
au marché, qui diffère justement entre les deux configurations.

Correctif (mesure identique pour les deux marchés, indépendante de `cfg`) :

```solidity
// setUp : l'attaquant est le SEUL déposant de chaque marché (assert explicite).
uint256 beforeBal = ghost.balanceOf(address(market));
_destroy(incidentId, targets);                       // [attaquant, marketWith, marketWithout]
uint256 burnedAtMarket = beforeBal - ghost.balanceOf(address(market));
// valeur réellement récupérable par le marché (prix fixe 1e18 -> 1e6, plancher 0) :
uint256 recoverableUsdc = ghost.balanceOf(address(market)) / 1e12;
uint256 badDebt = debt > recoverableUsdc ? debt - recoverableUsdc : 0;
console.log("bad debt (USDC units)", badDebt);
```

Assertions : `badDebtWith ≤ badDebtWithout` (qualitatif) ;
`burnedAtMarket == suspect entré chez le marché` mesuré **par le test** (delta de
`ghost.effectiveSuspectOf(market)` autour du dépôt, ou somme des `GhostTransferred.suspectMoved`),
à 1 wei par transfert près, pour **les deux** marchés ; `p.suspect == ce delta` seulement pour le
marché `useBeacon = true`. Écrire dans §8.3 que la valeur récupérable ne dépend pas de la
décote : la décote sert à prêter moins, pas à mesurer la perte.

### 2. MEDIUM — Affirmation « récupération » (§0bis, décision #37) : aucune mesure de la part récupérée

Où : §8.2 (c) (`testFuzz_suspicionConserved_chainAndFanOut` exclut explicitement destruction,
blanchiment et expiration), §8.3 (scénario D : un saut attaquant → pool → spéculateurs ; D2 :
fan-out avant vente). Aucun test ne nomme « part récupérée ».

Problème : la décision #37 sépare deux affirmations, chacune avec sa méthode de vérification.
La n°2 (« un transfert suspect est annulable tant que son Ghost n'est pas converti, **y compris
après fragmentation** ») se vérifie par « **rejeu d'une chaîne de transferts et mesure de la
part récupérée** ». Le design teste la conservation sans destruction et une destruction ponctuelle
(d). Il n'y a pas de test qui détruit le long d'une chaîne fragmentée et affiche ce qui a été
récupéré. `docs/CLAIMS.md` ne peut donc pas remplir la mesure de cette affirmation.

Correctif : ajouter dans `GhostGuardian.t.sol` (ou un `ScenarioRecovery.t.sol`) :

```solidity
/// Chaîne de profondeur `depth` puis fan-out `fanOut` depuis un compte marqué (Ghost volé),
/// confirmation 2/3 puis destructions par lots de MAX_BATCH sur tous les détenteurs.
function testFuzz_recovery_chainAndFanOut(uint8 depth, uint8 fanOut, uint256 seed) public {
    depth = uint8(bound(depth, 1, 32)); fanOut = uint8(bound(fanOut, 1, 16));
    // ... semis S, transferts, conversions "propres" tentées par les détenteurs ...
    // ... _confirm(id) puis _destroy(id, lot) pour chaque lot de 64 détenteurs ...
    assertEq(ghost.totalSuspectBurned(), S);          // rien de suspect n'a été converti
    console.log("recovered / seeded (1e18)", ghost.totalSuspectBurned() * 1e18 / S);
}
```

et une variante mesurée (`test_recovery_partialDetection`) où un tiers des détenteurs n'est pas
ciblé : la part récupérée est affichée, jamais assertée en dur (règle CLAIMS).

### 3. MEDIUM — `MockLendingMarket` : division par zéro sur une position sans jambe Ghost

Où : §5, « `ratioPos = suspect × 1e18 / ghost` » (utilisé par `haircutBps`, `collateralValue`
et `borrow`) et `withdraw` (« `suspect` diminue de `ceilDiv(ghostAmt × suspect, ghost)` »).

Problème : une position constituée uniquement de M (`p.ghost == 0`, `p.m > 0`) est exactement le
cas que le design met en avant (constat 4, `test_depositM_thenWithdraw_locked`). `ratioPos`
panique (0x12) dès qu'on emprunte contre cette position ou qu'on lit sa décote, et
`Math.ceilDiv(0, 0)` panique aussi au retrait de la seule jambe M. Le Ghost définit bien
« 0 si solde nul » pour `ratioOf`, mais pas le marché.

Correctif :

```solidity
uint256 ratioPos = p.ghost == 0 ? 0 : p.suspect * 1e18 / p.ghost;
// withdraw :
if (ghostAmt > 0) p.suspect -= Math.min(p.suspect, Math.ceilDiv(ghostAmt * p.suspect, p.ghost));
```

Test : dépôt M seul → `borrow` dans la limite LTV réussit, `haircutBps == base`, retrait de la
seule jambe M après `unlockAt` réussit.

### 3bis. MEDIUM — Divergences avec le registre de référence `data/ghost_ledger.py` non listées

Où : tout le design (aucune mention de `data/ghost_ledger.py` ni de `data/scenarios_cd.py`, arrivés
sur `main` par la PR #82, #25, propriétaire `data/` : Enzo). Lus sur `origin/main`.

Problème : le registre hors chaîne sert de référence aux scénarios C/D et de « point de
comparaison aux tests du contrat (#8) » (docstring du module). Le contrat doit lui rester fidèle
**ou** lister chaque divergence pour que le propriétaire de `data/` s'aligne. Le design diverge
sur plusieurs points de fond, sans les nommer :

| Point | `ghost_ledger.py` | Design | Effet si non signalé |
|---|---|---|---|
| Conversion | `convert(address)` convertit **toutes** les tranches échues ; le soupçon sort avec (`converted_suspect += ratio × matured`) | `convert(amount)`, verrou partiel : `amount ≤ min(matured, balanceOf − S)`, le soupçon ne sort **jamais** | C/D hors chaîne surestiment ce que l'attaquant sort ; (c) du contrat contredit le registre |
| Soupçon | un seul `float` permanent (`mark_suspect`) | `Sc` (confirmé) + `Sp` (en attente, expire avec l'incident) ; `Clear` 2/3 | silence = retour à 0 absent du registre |
| Retard | `delay(address, until)` libre ; `lift_delay` (levée multisig ou après destruction) | incident unique, `expiresAt` figé, borne `factor × W`, borne cumulée, budget ; **aucune levée**, `_extendedUntil` monotone | le registre modélise une action que le contrat interdit (veto asymétrique §3) |
| Destruction | `burn_suspect` : prorata des tranches, arrondi sur les plus récentes, arrondi `ceil` du soupçon | `Sc` seul, tranches les plus récentes d'abord | montants brûlés différents à 1 wei près et par tranche |
| Transfert du soupçon | `ratio × amount` en `float` | `ceilDiv` en entier, conservation exacte | écarts d'arrondi à tolérer dans les comparaisons |
| Mint | `mint(..., backed=False)` (fraude non adossée) | impossible on-chain (volet 1) ; `reserve()` saturée à 0, `totalIssued` = collatéral | `deficit > 0` du registre n'a pas d'équivalent on-chain hors hypothèse tombée |
| Marges | aucune | `entryFeeBps`, `convertFeeBaseBps/SlopeBps` (0 en fixtures) | à mettre à 0 pour comparer |
| Unités | seuil absolu `100 * 10**6` (6 déc.) | M / M-Ghost en 18 déc. | seuils incomparables tels quels |
| Marché (C) | « un coffre par prêt » (ratio par position) | une seule adresse, ratio mélangé, livre `p.suspect` | contagion entre déposants du marché absente du registre |
| Pool (D) | `ghost_price = 0.9` | prix fixe `usdcPerGhost` | à aligner via la fixture |
| Restitution, fonds d'assurance, pause | absents | présents | — |

Correctif : ajouter au design une section « Écarts avec `data/ghost_ledger.py` » reprenant ce
tableau (colonne « qui aligne » : `data/` sauf décision contraire), la recopier dans la
description de PR (§10, propriétaire `data/` à notifier), et ne **pas** modifier `data/`. Pour les
deux écarts qui touchent une décision (conversion du soupçon, `lift_delay`), écrire lequel est
fidèle à `OPEN_ANSWERS.md` : le design (verrou partiel ★ 3bis ; §3 « aucun acteur seul ne peut
raccourcir », §9 silence = retour auto). Facultatif mais utile : un test Foundry
`test_ledgerParity_simpleChain` qui rejoue une séquence courte (mint, 2 transferts, conversion)
sans marquage ni marge et vérifie l'égalité des soldes / échéances avec les valeurs attendues du
registre recopiées en dur dans le test.

### 3ter. MEDIUM — Compatibilité avec `monitor/listener.py` : sens des `Transfer` et id de demande non spécifiés

Où : §2 (M brûlé + Ghost émis), §3.9, §3.12 (événements), §7 (`SwapCompleted` inchangé), §10
(proposition monitor). Lu : `monitor/listener.py` sur `origin/main`.

Ce qui est déjà conforme (vérifié) : M-Ghost est une adresse ERC-20 **distincte** de M
(`GhostToken` vs `GhostedStable`), héritée d'OZ `ERC20`, donc `Transfer(address,address,uint256)`
standard avec mint = `from 0x0` et brûlage / destruction = `to 0x0` ; `RoleGranted` (OZ
`AccessControl`, y compris `WATCHER_ROLE` sur le Ghost) et `RateChanged` existent ;
`PerimeterDelayed` (marquage + retard), `IncidentOpened`, `GhostDestroyed`, `Restituted`,
`GhostConverted`, `SuspicionCleared` sont des événements dédiés.

Problème : le listener classe tout `Transfer(0x0, to)` d'un token comme un **mint**
(`decode_erc20_mint`, `request_id = UNKNOWN_REQUEST_ID`) et exclut les `to == 0x0`. Avec ce design :

- sur **M**, il n'y a plus jamais de `Transfer(from, to)` : un transfert de M donne
  `Transfer(from, 0x0, v)` (exclu) ; chaque `Transfer(0x0, a)` est une **conversion**, pas un mint ;
- sur **M-Ghost**, `Transfer(0x0, to)` couvre trois cas : mint du minter, transfert de M, restitution ;
- l'événement de mint qui porte l'id de demande (`SwapCompleted(requestId, depositor, recipient,
  depositAmount, mintedAmount, rate)`) est émis par **`ProtectedMinter`**, pas par le token écouté ;
  `GhostIssued(kind = MINT)` ne porte pas `requestId`.

Le design ne dit rien de cette correspondance : le détecteur de mint (#9) compterait chaque
conversion et chaque transfert de M comme un mint, et le détecteur de transferts (#10) ne verrait
aucun transfert de M.

Correctif :

1. Ajouter `requestId` à l'émission minter, sans changer `SwapCompleted` :
   ```solidity
   event GhostIssued(address indexed recipient, address indexed source, uint256 indexed requestId,
                     uint256 amount, uint256 incomingRatio, uint64 maturity, IssueKind kind);
   // issueFromMinter(address to, uint256 amount, uint256 requestId) ; requestId = 0 hors MINT
   // (ProtectedMinter.completeSwap passe requestId ; ids de demande à partir de 0 aujourd'hui :
   //  soit décaler nextRequestId à 1, soit ajouter un booléen / utiliser type(uint256).max hors MINT).
   ```
   et écrire dans §7 que `SwapCompleted` (adresse du minter) reste l'événement de référence
   « demande n°X → déposant → montant » pour le décodeur dédié du monitor.
2. Ajouter une table « Lecture monitor par adresse » en §3.12 :

   | Adresse | Log | Sens |
   |---|---|---|
   | M-Ghost | `Transfer(0x0, to)` + `GhostIssued(kind)` dans la même tx | MINT (avec `requestId`) / TRANSFER_M (`source` = expéditeur M) / RESTITUTION |
   | M-Ghost | `Transfer(from, to)` | transfert de Ghost (`is_ghost = true`) |
   | M-Ghost | `Transfer(a, 0x0)` + `GhostConverted` / `GhostDestroyed` | conversion / destruction |
   | M | `Transfer(from, 0x0)` + `GhostIssued(TRANSFER_M)` côté Ghost | transfert de M (`is_ghost = false`), à reconstruire depuis `GhostIssued.source → recipient` |
   | M | `Transfer(0x0, a)` | conversion, **jamais** un mint |
   | ProtectedMinter | `SwapCompleted` | mint (id de demande) |

3. Reporter cette table dans la description de PR pour #9 / #10 (le décodeur ERC-20 générique ne
   doit pas être branché sur M comme détecteur de mint ; `token_is_ghost = true` pour l'adresse
   M-Ghost seulement).

Test : `test_events_monitorMapping` vérifie (`vm.expectEmit`) la suite exacte de logs pour un mint,
un transfert de M, un transfert de Ghost, une conversion et une destruction, y compris
`GhostIssued.requestId` égal à l'id de `SwapCompleted`.

### 4. NIT — Incohérence sur la minuterie de la réserve après un transfert de M

§3.7 et §9-9 : « chaque `convert` **ou transfert de M** repousse `lastReserveInflowAt` ».
§3.9 `onUnderlyingTransfer` ne fait que `totalFees += fee`. Ajouter dans §3.9 :
`if (fee > 0) lastReserveInflowAt = uint64(block.timestamp);`.

### 5. NIT — Acteur des événements de la voie `Extend` 2/3

§3.6bis : `actor = address(this)` pour `Extend`, mais §3.4 émet `IncidentOpened(id, msg.sender, …)`
et `PerimeterDelayed(…, msg.sender, …)`. À l'exécution 2/3, `msg.sender` est le 2e guardian.
Passer l'acteur explicitement : `_delay(accounts, amounts, duration, bool checkBudget, address actor)`,
`delay` → `actor = msg.sender`, `Extend` → `actor = address(this)`.

### 6. NIT — Le surveillant ne peut pas lire la borne cumulée

§3.4 / §3.11 : la vue `extendedUntil(a)` renvoie 0 après expiration, donc un surveillant
off-chain ne sait pas si le cooldown W est écoulé (`now ≥ _extendedUntil + W`) ni jusqu'où il peut
encore allonger. Il ne le découvre que par un revert `ExtensionTooLong` qui annule tout le lot.
Ajouter une vue :

```solidity
function maxExtensionEnd(address a) external view returns (uint64) {
    uint256 start = (_extendedUntil[a] == 0 || block.timestamp >= uint256(_extendedUntil[a]) + window)
        ? block.timestamp : extensionRunStart[a];
    return uint64(start + uint256(maxExtensionFactor) * window);
}
```

### 7. NIT — Énoncé honnête de la friction max par compte

§3.4 / §10 (« friction max par compte = factor × W par série ») : avec un cooldown de W, un
surveillant compromis peut retarder un compte `factor × W` sur chaque période de
`(factor + 1) × W`, indéfiniment (6/7 du temps avec les fixtures). C'est borné, mais pas en durée
totale. Écrire la borne sous forme de taux (`factor / (factor + 1)`) dans le README et dans le ★ 3ter,
pour que `docs/CLAIMS.md` ne lise pas « friction bornée » comme « durée bornée ».

### 8. NIT — Interaction `Extend` 2/3 ↔ incident courant non décrite

§3.6bis : `Extend` appelle `_delay(…, false)`. S'il existe un incident vivant non confirmé, il le
**rejoint** : `duration` est ignorée (les humains ne peuvent pas allonger au-delà de
`expiresAt`), et les soldes ajoutés entrent dans `extendedBalance`. Après un `Extend` hors budget,
chaque `delay` du surveillant revert `QuarantineBudgetExceeded` jusqu'à `expiresAt`. C'est
conforme à « au-delà, extension = humain requis » (§9), mais à écrire en §3.6bis et au README,
avec un test `test_extendOverBudget_blocksWatcherUntilExpiry`.

### 9. NIT — `Risk.incidentId` sans source définie

§4 : `Risk { …; uint64 windowExpiresAt; …; uint256 incidentId; }`. `windowExpiresAt` correspond
à `extendedUntil(a)` (cohérent avec `RiskBeaconUpdate.window_expires_at`, « fin de fenêtre
allongée en cours »). `incidentId` peut venir de `pendingTag`, `extensionTag` ou
`destroyedIncident`. Fixer la règle : `DETRUIT` → `destroyedIncident(a)` ; `RETARDE` →
`extensionTag(a)` ; sinon `pendingTag` valide ou 0. Fixer aussi `suspectAmount =
effectiveSuspectOf(a)` et `ratio = ratioOf(a)`.

### 10. NIT — Arrondis côté seuils et créances

- §3.5 étape 4 : `ratio = S × 1e18 / balanceOf` arrondi bas laisse passer un ratio un peu
  au-dessus du seuil. Utiliser `Math.mulDiv(S, 1e18, balanceOf, Math.Rounding.Ceil)` pour la
  comparaison (sens sûr), garder l'arrondi bas pour la marge.
- §6 : préciser `ratioConfirmed = ceil(Sc × 1e18 / B)` et `ratioPending = ceil(Sp × 1e18 / B)`
  (sens sûr pour l'annulation), et que `pendingTag == 0` compte comme « ni confirmé ni vivant ».

### 11. NIT — Ordre `_moveBuckets` / contrôle de solde

§3.9 : `_moveBuckets` et le déplacement de soupçon s'exécutent avant `super._update`. Un envoi
supérieur au solde panique dans la librairie au lieu de renvoyer `ERC20InsufficientBalance`
(annoncé en §3.13). Ajouter en tête de la branche transfert :
`if (balanceOf(from) < v) revert ERC20InsufficientBalance(from, balanceOf(from), v);`
(et mettre `B` en cache avant toute écriture).

### 12. NIT — `nextOutgoingMaturity` : règlement virtuel à préciser

§3.11 / §6 : le pool lit `nextOutgoingMaturity(seller, v)` avant le transfert, sans `_settle`.
Écrire que la vue traite comme échues les tranches `maturity ≤ now` (comme
`maturedEffectiveOf`), sinon l'échéance de créance est surestimée. Test : tranche échue non
réglée, vente, `claim.maturity == now`.

### 13. NIT — Repli `GhostLens` : interface incomplète

§1 repli 2 / §6 : `GhostUsdcPool` reçoit un seul `IGhostRisk ghostRisk` (« le Ghost, ou
`GhostLens` »), mais lit aussi `paused`, `destroyedAt`, `clearedAt`, `incidents`, `extendedUntil`.
Écrire que `GhostLens` implémente **tout** `IGhostRisk` (vues déplacées calculées sur les
getters bruts, autres vues relayées vers le Ghost), ou que pool et balise reçoivent deux adresses.

### 14. NIT — Validation « à la proposition et à l'exécution » à découper

§3.13 : certaines conditions dépendent de l'état à l'exécution (`ExceedsReserve`,
`IncidentExpired`, borne cumulée, `EnforcedPause`). Les vérifier à la proposition refuserait par
exemple une restitution proposée avant que la réserve ne soit alimentée. Lister : à la proposition
= contrôles sans état (`BatchTooLarge`, `LengthMismatch`, `ZeroAddress`, `ZeroAmount`,
`InvalidDuration`, `duration ≤ factor × W`, `1 ≤ incidentId ≤ openIncidentId`) ; à l'exécution =
tout, y compris l'état.

### 15. NIT — Marché : positions non dépréciées après destruction

§5 : une destruction qui vise le marché baisse son solde Ghost, mais `p.ghost` / `p.m` ne
changent pas. `Σ positions > ghost.balanceOf(market)` et le dernier retrait revert
(`ERC20InsufficientBalance`). Hors périmètre (pas de liquidation), mais à écrire dans les limites
du README. C'est aussi pour cela que la mesure du constat 1 lit le solde réel du marché.

## Couverture demandée (checklist)

| Point | Couvert ? | Où |
|---|---|---|
| Échéance jamais remise à zéro par la circulation ; seuls mint / transfert de M (et restitution) posent `now + W` | Oui | §2, §3.2, §3.7, §3.9 |
| N créneaux fixes, arrondi supérieur, plus anciennes d'abord | Oui (preuve N+1 revérifiée) | §3.2 |
| Conversion : tranche échue ET non allongé ET seuils ratio / absolu | Oui (+ verrou partiel) | §3.5 ; NIT 10 (arrondi) |
| Ratio pondéré 1e18, conservation | Oui (calcul revérifié) | §3.3 |
| Surveillant : actions sûres, auto-expirantes, facteur max, budget, expiration O(1) / paresseuse | Oui | §3.4 ; NIT 6, 7, 8 |
| Destruction 2/3 = ratio confirmé × non converti, jamais de M repris | Oui | §3.6 |
| Solvabilité, réserve ≥ 0, restitution plafonnée | Oui | §1, §3.7, (e) ; NIT 4 |
| Pause 3/3 via `GuardianPausable` | Oui | §3.8 |
| RiskBeacon : lecture, états, permissions §3 | Oui | §4 ; NIT 9 |
| Marché : décote par balise + config sans balise | Oui, formule à corriger | §5 ; constat 3, NIT 15 |
| Pool : règlement différé `swapId`, annulation ratio × montant | Oui | §6 ; NIT 10, 12 |
| Invariants (a)–(g), vivacité sans revert avalé, gas N tranches | Oui | §8.2, §8.4 |
| Scénarios C et D | D oui ; **C : métrique invalide** | §8.3 ; constat 1 |
| Affirmation « récupération » (#37) mesurée | **Non** | constat 2 |
| Cohérence avec `data/ghost_ledger.py` ou divergences listées | **Non** | constat 3bis |
| Événements lisibles par `monitor/listener.py` (Transfer standard, mint avec `requestId`, événements dédiés) | **Partiel** | constat 3ter |
| Périmètre `contracts/` seul, choix à valider listés (★) | Oui | §9, §10, §13 |

## Hypothèses vérifiées

- **Itération 1 traitée** : verrou partiel `amount ≤ balanceOf − S` (constat 1) ; borne cumulée
  par compte avec `_extendedUntil == 0` géré (2) ; `_extendedUntil` monotone (3) ; `unlockAt`
  unique posé par tout dépôt (4) ; `extendedBalance` mis à jour dans toutes les branches de
  `_update` et comparé au modèle d'ombre (5) ; destruction de `Sc` seul et annulation de
  `rConfirmed` seule (6) ; `Extend` 2/3 (7) ; compte détecté tard documenté + mesuré (8) ; delta
  `beacon.riskOf(market)` seulement si `useBeacon` (9) ; ordre des replis de taille (10) ; NIT
  11–22 repris.
- **Compilation** : un contrat sonde `is ERC20, AccessControl, <abstract> is GuardianPausable`,
  avec `_update` surchargé appelant `_requireNotPaused()` et une erreur
  `ActionAlreadyApproved(address,uint256)`, compile avec la chaîne du projet (solc 0.8.33, OZ
  5.4.0). Le `_approve(bool)` **privé** de `GuardianPausable` ne gêne pas les
  `_approve(address,address,uint256[,bool])` d'`ERC20`. Sonde supprimée après coup.
- `GuardianPausable` : abstrait, `onlyGuardian`, `isGuardian` public, `pauseRound` / `approvals`,
  `AlreadyApproved` déjà déclaré (d'où `ActionAlreadyApproved`), `approvePause` `whenNotPaused`,
  `approveUnpause` `whenPaused`.
- `ProtectedMinter` : constructeur à 5 arguments, `stable = new StableToken(...)` dans le
  constructeur, un seul appel `stable.mint(depositor, minted)` dans `completeSwap`,
  `totalMinted` public. La cascade de déploiement et `totalIssued == totalMinted` sont réalistes.
- Lignes citées en §8.1 exactes : `GuardianPausable.t.sol` l. 122 et 125 ;
  `ProtectedMinter.t.sol` l. 149 (`StableToken.NotMinter`) et l. 211, 216, 222 (constructeur) ;
  `StolenServiceKey.fuzz.t.sol` l. 76. `ProtectedMinterHandler.stolenKeyMintDirect` existe ;
  l'invariant volet 1 compte 7 invariants + `invariant_callSummary`. `Tokens.t.sol` et
  `VulnerableMinter.t.sol` n'utilisent que `StableToken` / `VulnerableMinter` : ils ne bougent pas.
- `foundry.toml` : solc 0.8.33, cancun, optimizer 200, `fail_on_revert = false` ; OZ 5.4.0
  (`SafeCast`, `Math.ceilDiv`, `Pausable._requireNotPaused` présents).
- Arithmétique du soupçon : `moved ≤ v`, `movedC ≤ moved`, `movedP ≤ Sp`, `Sc + Sp ≤ balanceOf`
  conservé des deux côtés (`v − moved ≤ B − S`), somme conservée exactement ; semis
  `min(amount, balanceOf − Sc)` garde la borne ; conversion bornée par `balanceOf − S` et
  destruction de `Sc` gardent `S ≤ balanceOf`.
- Un seul incident non confirmé vivant à la fois (ouverture seulement si `openIncidentId` est
  confirmé ou expiré) : la fusion des `pendingTag` après `_normalize` est sûre, `Extend` compris.
- Borne cumulée : une série d'un compte ne dépasse pas `runStart + factor × W` ; deux séries sont
  séparées d'au moins W (enchaînement au bloc d'expiration → revert).
- Solvabilité : `restitution ≤ reserve()` ⇒ `supplyValue + insuranceFund ≤ totalIssued` ;
  marges et destructions ne font que baisser `supplyValue`.
- `docs/CONTRACTS.md` : `RiskBeaconUpdate.window_expires_at` = « fin de fenêtre allongée en
  cours » (d'où NIT 9 limité à `incidentId`).
- `monitor/listener.py` (`origin/main`) : filtre par adresse de token, topic0
  `Transfer(address,address,uint256)` à 3 topics, mint = `from 0x0`, burns exclus,
  `is_ghost` pris dans la config par token, décodeur de mint dédié prévu (`mint_decoders`).
  M et M-Ghost du design sont deux adresses ERC-20 OZ distinctes : compatibles avec ce décodage
  (le sens des logs reste à documenter, constat 3ter).
- `ProtectedMinter.requestSwap` : `requestId = nextRequestId++` avec `nextRequestId` initial 0,
  donc la première demande porte l'id 0.

## Hypothèses non vérifiées ou fausses

- **Fausse** : la mesure du scénario C compare « avec vs sans balise » — avec `Position.suspect`,
  le marché sans balise affiche toujours 0 (constat 1).
- **Fausse** : `ratioPos` est défini pour toute position — pas si `p.ghost == 0` (constat 3).
- **Non couverte** : la mesure de la part récupérée après fragmentation exigée par #37 (constat 2).
- **Fausse (implicite)** : un `Transfer(0x0, to)` signifie « mint » pour le monitor — faux sur M
  (conversion) et ambigu sur M-Ghost (mint / transfert de M / restitution) ; et l'id de demande 0
  existe (`nextRequestId` part de 0) alors que le listener utilise 0 comme sentinelle
  `UNKNOWN_REQUEST_ID` (constat 3ter).
- **Non signalée** : le registre `data/ghost_ledger.py` modélise `lift_delay` et une conversion
  qui emporte le soupçon, deux comportements que le contrat interdit (constat 3bis).
- **Non vérifiée** : tailles runtime / initcode réelles sous EIP-170 / EIP-3860 (aucun code
  Ghost à compiler ; replis prévus).
- **Non vérifiée** : que Foundry lie une librairie externe dans l'initcode imbriqué
  `ProtectedMinter → GhostToken` (repli 1). Plausible (les `linkReferences` de solc couvrent le
  bytecode imbriqué), à confirmer au premier `forge build` si le repli est déclenché.
- **Non vérifiée** : coût gas du pire cas N = 10 (mesure prévue §8.4).
- **Non revérifiée** : le contenu des issues #8, #7, #65, #33 (le design dit les avoir lues ; cette
  revue s'appuie sur `OPEN_ANSWERS.md`, qui fait foi).
